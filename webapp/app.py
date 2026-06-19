"""Flask 应用：静态前端 + JSON API。

启动：
    python -m webapp                 # 开发服务器，默认 http://127.0.0.1:5000
    python -m fund_analyzer serve    # 同上（CLI 子命令）
    gunicorn wsgi:app                # 生产部署（见 DEPLOY.md）

访问保护（公网部署务必开启）：
    设置环境变量 APP_PASSWORD 后，全站启用 HTTP Basic 认证；
    APP_USERNAME 可选（默认任意用户名 + 正确密码即可）。健康检查 /api/health 不需要认证。
"""
from __future__ import annotations

import os
import traceback

from flask import Flask, Response, jsonify, request, send_from_directory

from . import service

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def _auth_ok() -> bool:
    pw = os.getenv("APP_PASSWORD")
    if not pw:
        return True  # 未设置密码 → 不启用认证（仅建议本机使用）
    expected_user = os.getenv("APP_USERNAME", "")
    auth = request.authorization
    if not auth:
        return False
    user_ok = (not expected_user) or (auth.username == expected_user)
    return bool(user_ok and auth.password == pw)


def create_app() -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")

    @app.before_request
    def _guard():
        if request.path == "/api/health":
            return None
        if not _auth_ok():
            return Response("需要登录", 401,
                            {"WWW-Authenticate": 'Basic realm="fund-analyzer"'})
        return None

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/api/report")
    def report():
        mode = request.args.get("mode", "demo")
        try:
            data = service.build_demo_json() if mode == "demo" else service.build_live_json()
            return jsonify(data)
        except Exception as e:  # 任何异常都转成可读 JSON，避免前端崩
            traceback.print_exc()
            return jsonify({"error": str(e), "mode": mode}), 500

    @app.get("/api/holdings")
    def get_holdings():
        return jsonify({"holdings": service.read_holdings_raw()})

    @app.get("/api/holdings/example")
    def get_example():
        return jsonify({"holdings": service.read_example_holdings()})

    @app.post("/api/holdings")
    def post_holdings():
        body = request.get_json(silent=True) or {}
        holdings = body.get("holdings", [])
        if not isinstance(holdings, list):
            return jsonify({"error": "holdings 应为数组"}), 400
        try:
            n = service.save_holdings(holdings)
            return jsonify({"ok": True, "saved": n})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.post("/api/email/test")
    def email_test():
        from fund_analyzer.config import load_email_config
        from fund_analyzer.emailer import send_email
        cfg = load_email_config()
        if not cfg.configured:
            return jsonify({"ok": False, "message": "邮件未配置（需设置 SMTP_* 环境变量）"}), 400
        ok = send_email(cfg, "【测试】基金分析助手邮件配置成功",
                        "<h3>配置成功 ✅</h3><p>每日报告可正常发送。</p>", "配置成功")
        return jsonify({"ok": ok})

    # ---- 导入 ----

    @app.post("/api/import/ocr")
    def import_ocr():
        if "image" not in request.files:
            return jsonify({"error": "请上传截图文件"}), 400
        file = request.files["image"]
        try:
            data = file.read()
            results = service.ocr_import(data)
            return jsonify({"ok": True, "funds": results, "count": len(results)})
        except RuntimeError as e:
            return jsonify({"error": str(e) + "（请确保已安装 tesseract-ocr 和 pytesseract）"}), 500
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"OCR 识别失败: {e}"}), 500

    @app.post("/api/import/batch")
    def import_batch():
        body = request.get_json(silent=True) or {}
        text = body.get("text", "")
        if not text.strip():
            return jsonify({"error": "请提供批量导入文本（每行: 代码 金额 每日定投额）"}), 400
        from fund_analyzer.importer import parse_batch_text
        pairs = parse_batch_text(text)
        if not pairs:
            return jsonify({"error": "未识别到有效的基金代码和金额，格式：代码 金额 每日定投额（空格分隔）"}), 400
        codes = [p[0] for p in pairs]
        amount_map = {p[0]: p[1] for p in pairs}
        dca_map = {p[0]: p[2] for p in pairs if p[2] > 0}
        funds = service.batch_auto_fill(codes)
        for f in funds:
            f["current_value"] = amount_map.get(f["code"], 0)
            f["is_dca"] = True
            if f["code"] in dca_map:
                f["dca_plan"] = {"frequency": "daily", "amount": dca_map[f["code"]], "enabled": True}
        return jsonify({"ok": True, "funds": funds, "count": len(funds)})

    @app.get("/api/fund/search")
    def fund_search():
        code = request.args.get("code", "").strip()
        if not code or len(code) != 6:
            return jsonify({"error": "请输入6位基金代码"}), 400
        info = service.auto_fill_fund(code)
        if not info:
            return jsonify({"error": f"未找到基金 {code}，请确认代码正确"}), 404
        return jsonify({"fund": info})

    # ---- AI 分析 ----

    @app.get("/api/ai/analyze")
    def ai_analyze():
        """对已保存的持仓运行 AI 分析。需要 DEEPSEEK_API_KEY。"""
        try:
            holdings = service.read_holdings_raw()
            if not holdings:
                return jsonify({"error": "请先保存持仓"}), 400
            result = service.run_ai_analysis(holdings)
            return jsonify(result)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ---- 自选基金分析 ----

    @app.get("/api/watchlist/analyze")
    def watchlist_analyze():
        """分析自选基金：看好/不看好 + 适合买入吗。支持 ?code=270042 或 ?codes=270042,050025"""
        raw = request.args.get("codes") or request.args.get("code", "")
        codes = [c.strip() for c in raw.split(",") if c.strip() and len(c.strip()) == 6]
        if not codes:
            return jsonify({"error": "请提供基金代码，如 ?codes=270042,050025"}), 400
        try:
            results = service.analyze_watchlist(codes)
            return jsonify({"ok": True, "results": results})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    return app
