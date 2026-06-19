"""生产部署入口（gunicorn / uWSGI 等 WSGI 服务器使用）。

例：  gunicorn -b 0.0.0.0:$PORT -w 2 --timeout 120 wsgi:app
"""
from webapp.app import create_app

app = create_app()
