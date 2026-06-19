"""webapp —— 基金分析系统的可视化网站（Flask）。

- 复用 fund_analyzer 的全部分析逻辑，只在其上加一层 HTTP + JSON API + 前端页面；
- 自带「演示模式」（无需联网、无需配置即可看完整 UI）；
- 前端为零依赖的原生 HTML/CSS/JS + 手写 SVG 图表（不依赖任何 CDN，适合国内网络）。

注意：本 __init__ 刻意不在顶层导入 Flask，使得 webapp.service / webapp.serialize
可在不安装 Flask 的情况下被复用与测试。需要应用对象时请 `from webapp.app import create_app`。
"""

__all__ = ["service", "serialize"]
