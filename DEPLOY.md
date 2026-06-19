# 部署指南（把网站放到公网，手机随时打开）

本项目是个标准的 Python/Flask 应用，可以部署到几乎任何地方。下面给出**从最省事到最可控**的几种方案。

---

## ⚠️ 部署前必读（三件事）

1. **一定要设密码**：公网上是你的持仓和盈亏，且「持仓管理」能改数据。务必设置环境变量
   `APP_PASSWORD`（可选 `APP_USERNAME`），全站会启用登录认证。不设密码＝任何人都能看你的账户。
2. **持仓怎么不丢**：很多免费平台「文件系统是临时的」，重启就清空。两种持久化办法（任选其一）：
   - 设环境变量 `HOLDINGS_YAML`：把你 `config/holdings.yaml` 的**全文**粘进去，应用启动时会自动落地；
   - 或挂一块**持久盘**，并设 `HOLDINGS_PATH=/data/holdings.yaml`（如 Fly.io 方案）。
3. **服务器要能联网取数**：应用要访问天天基金和 Yahoo 行情。境外服务器（新加坡/东京/香港）都能访问，
   没问题；国内服务器访问 Yahoo 可能需要自备网络方案（也可改用其它指数源）。

---

## 方案 A：Render（免费、最省事，推荐先用这个）

无需自己的服务器，连上 GitHub 仓库点几下就上线。

1. 注册 https://render.com （可用 GitHub 账号登录）。
2. 控制台 **New +** → **Blueprint** → 选择本仓库（已内置 `render.yaml`）→ Apply。
   - 或 **New +** → **Web Service** → 连接仓库，构建命令 `pip install -r requirements-deploy.txt`，
     启动命令 `gunicorn -b 0.0.0.0:$PORT -w 2 --timeout 120 wsgi:app`。
3. 在服务的 **Environment** 里填：
   - `APP_PASSWORD` = 你的登录密码（必填）
   - `HOLDINGS_YAML` = 你的持仓 YAML 全文（免费档无持久盘时用它保存持仓）
   - 想线上也发邮件：再填 `SMTP_PROVIDER`/`SMTP_USER`/`SMTP_PASSWORD`/`MAIL_TO`
4. 部署完成后会给你一个网址 `https://xxx.onrender.com`，手机浏览器打开、输入密码即可。

> 免费档说明：**闲置一段时间会休眠**，下次打开冷启动约 30 秒；文件系统临时（所以用 `HOLDINGS_YAML`）。
> 介意休眠就升级到付费档，或用下面的自有服务器方案。

---

## 方案 B：自己的服务器 / VPS（用 Docker，最稳、可绑域名、适合国内）

有一台云服务器（阿里云/腾讯云/Vultr/搬瓦工等）时，一条命令跑起来：

```bash
# 在服务器上
git clone <你的仓库地址> fund-analyzer && cd fund-analyzer
docker build -t fund-analyzer .
docker run -d --name fund-analyzer -p 80:8000 --restart unless-stopped \
  -e APP_PASSWORD='你的密码' \
  -e HOLDINGS_PATH='/data/holdings.yaml' \
  -v /opt/fund-data:/data \
  fund-analyzer
```

- `-v /opt/fund-data:/data` 是**持久盘**，保存的持仓不会丢。
- 然后浏览器打开 `http://服务器IP`，输入密码即可。
- 想要 HTTPS + 域名：前面加个 Nginx/Caddy 反向代理（Caddy 可自动签发证书）。

不想用 Docker 也可以直接裸跑：

```bash
pip install -r requirements-deploy.txt
APP_PASSWORD='你的密码' gunicorn -b 0.0.0.0:8000 -w 2 --timeout 120 wsgi:app
# 建议配合 systemd / pm2 / supervisor 守护进程
```

---

## 方案 C：Railway（和 Render 类似，按用量计费）

1. https://railway.app 用 GitHub 登录 → New Project → Deploy from GitHub repo。
2. Railway 会识别 `Procfile`/`Dockerfile` 自动部署。
3. Variables 里设 `APP_PASSWORD`、`HOLDINGS_YAML`（及可选 SMTP_*）。
4. Settings → Networking → Generate Domain 得到公网网址。

---

## 方案 D：Fly.io（有持久盘、离中国近）

```bash
# 安装 flyctl 后
flyctl auth login
flyctl launch --no-deploy          # 会读取仓库里的 fly.toml
flyctl volumes create fund_data --size 1 --region nrt   # 持久盘（保存持仓）
flyctl secrets set APP_PASSWORD=你的密码
flyctl deploy
```

`fly.toml` 已配好 `HOLDINGS_PATH=/data/holdings.yaml` + 持久盘挂载，持仓不会丢。

---

## 每日邮件还要不要？

部署的是「随时打开看」的网站；**每天定时发邮件**仍然用仓库里的 GitHub Actions
（`.github/workflows/daily-report.yml`）最省心——两者互不冲突，可同时用。详见 README「让它每天自动发邮件」。

---

## 本地先验证（部署前自检）

```bash
pip install -r requirements-deploy.txt
APP_PASSWORD=test gunicorn -b 127.0.0.1:8000 -w 2 wsgi:app
# 另开终端：
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/            # 401（需密码）
curl -s -u :test -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/   # 200
curl -s http://127.0.0.1:8000/api/health                                   # {"ok":true}
```
