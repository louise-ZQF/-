"""`python -m webapp` 启动开发服务器。"""
from __future__ import annotations

import os

from .app import create_app


def main():
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    app = create_app()
    print(f"基金分析网站已启动 →  http://{host}:{port}")
    print("（默认仅本机可访问；演示模式无需任何配置，直接打开即可看效果）")
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
