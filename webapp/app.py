"""Flask 应用：静态前端 + JSON API。

启动：
    python -m webapp                 # 默认 http://127.0.0.1:5000
    python -m fund_analyzer serve    # 同上（CLI 子命令）
"""
from __future__ import annotations

import os
import traceback

from flask import Flask, jsonify, request, send_from_directory

from . import service

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def create_app() -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")

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
        except Exception as e:  # 任何异常都转成可读的 JSON，避免前端崩
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

    return app
