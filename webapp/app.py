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

    # ---- 自选基金 ----

    @app.get("/api/watchlist")
    def get_watchlist():
        """读取自选列表。"""
        try:
            items = service.get_watchlist()
            return jsonify({"ok": True, "watchlist": items})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.post("/api/watchlist")
    def post_watchlist():
        """添加/更新自选基金。"""
        body = request.get_json(silent=True) or {}
        try:
            result = service.add_watch_item(body)
            return jsonify(result)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.delete("/api/watchlist")
    def delete_watchlist():
        """从自选列表删除。?code=270042"""
        code = request.args.get("code", "").strip()
        if not code:
            return jsonify({"error": "请提供 code 参数"}), 400
        try:
            result = service.remove_watch_item(code)
            return jsonify(result)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @app.get("/api/watchlist/analyze")
    def watchlist_analyze():
        """分析自选：质量×择时决策 + 持仓相关性。?codes=270042,050025"""
        raw = request.args.get("codes") or request.args.get("code", "")
        codes = [c.strip() for c in raw.split(",") if c.strip() and len(c.strip()) == 6]
        if not codes:
            return jsonify({"error": "请提供基金代码，如 ?codes=270042,050025"}), 400
        try:
            data = service.analyze_watchlist_full(codes)
            return jsonify({"ok": True, "results": data.get("results", []), "alerts": data.get("alerts", [])})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ---- 基金筛选 ----

    @app.get("/api/screener/<category>")
    def screener(category):
        """筛选基金: ?category=us-qdii|a-stock"""
        valid = {"us-qdii": "us_qdii", "a-stock": "a_stock"}
        cat = valid.get(category)
        if not cat:
            return jsonify({"error": "请指定 category=us-qdii 或 a-stock"}), 400
        try:
            results = service.run_screener(cat)
            return jsonify({"ok": True, "funds": [
                {"code": f.code, "name": f.name, "fund_type": f.fund_type,
                 "ret_1y": f.ret_1y, "ret_3y": f.ret_3y, "sharpe": f.sharpe,
                 "max_dd": f.max_dd, "vol_annual": f.vol_annual,
                 "factor_score": f.factor_score, "recommendation": f.recommendation}
                for f in results
            ], "count": len(results)})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ---- 智能提醒 ----

    @app.get("/api/alerts")
    def alerts():
        """持仓智能提醒。"""
        try:
            holdings = service.read_holdings_raw()
            if not holdings:
                return jsonify({"error": "请先保存持仓"}), 400
            result = service.generate_alerts(holdings)
            return jsonify({"ok": True, "alerts": [
                {"code": a.code, "name": a.name, "alert_type": a.alert_type,
                 "level": a.level, "message": a.message, "action": a.action}
                for a in result
            ]})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ---- XIRR 真实收益 ----

    @app.get("/api/xirr")
    def xirr():
        """计算投资组合 XIRR 真实年化收益。"""
        try:
            result = service.compute_xirr()
            return jsonify({"ok": True, **result})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ---- 收益曲线 ----

    @app.get("/api/snapshot/curve")
    def snapshot_curve():
        """获取收益曲线数据。?days=90"""
        days = request.args.get("days", 90, type=int)
        try:
            data = service.get_return_curve(days)
            return jsonify({"ok": True, "curve": data})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ---- 真实估值 ----

    @app.get("/api/valuation/<code>")
    def valuation(code):
        """获取基金真实 PE/PB 估值分位。"""
        try:
            data = service.get_valuation(code)
            return jsonify({"ok": True, **data})
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    # ---- PWA manifest ----

    @app.get("/manifest.json")
    def manifest():
        return jsonify({
            "name": "基金组合分析",
            "short_name": "基金分析",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#f4f6f9",
            "theme_color": "#2563eb",
            "icons": [{"src": "/static/icon.svg", "sizes": "192x192", "type": "image/svg+xml"}],
        })

    return app
