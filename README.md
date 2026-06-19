# 基金组合智能分析与每日建议系统（fund-analyzer）

一个面向**以美股 QDII 为主、A 股为辅**的个人基金组合的自动分析工具。它每天为你做两件事：

1. **每日操作建议** —— 把你的持仓导入，结合估值分位、趋势、RSI、最大回撤、夏普、持仓盈亏等指标，
   按公开成熟的基金投资规则（估值定投 / 目标止盈 / 回撤止盈 / 再平衡）给出**每只基金「买入 / 继续定投 /
   持有 / 暂停定投 / 减仓止盈 / 卖出」的建议**，并解释理由。
2. **QDII「T+时差」收益估算** —— 国内 QDII 基金净值 T+1/T+2 才更新，美股今晚涨跌要过 1~2 天才体现到
   净值上。本工具直接用**已经发生的美股指数涨跌**，估算你的基金「应有净值」和「其实今天已经赚/亏了多少」，
   还给出误差带。

报告可生成 Markdown / HTML，并**自动发送到你的邮箱（QQ / 163 均可）**。

> ⚠️ **免责声明**：本项目所有指标、估算与「操作建议」都是**基于公开数据和通用规则的量化参考，不构成任何
> 投资建议**。时差估算是近似模型，必有误差。市场有风险，决策请独立判断、自负盈亏。

---

## 30 秒看效果（无需联网、无需配置）

```bash
pip install -r requirements.txt
python -m fund_analyzer demo
```

会用内置的「拟真」示例数据跑通全流程，在终端打印中文报告，并在 `output/` 下生成 `.md` 和 `.html`。
你会看到类似：

```
## 一、组合概览
- 已公布净值市值：¥46,195.80
- 时差估算「应有」市值：¥46,969.70（估算当日额外涨跌 +1.68%，即美股已发生但基金净值尚未体现的部分）
...
### （示例）纳指100指数QDII（270042）— us_equity
- 操作建议：部分止盈/减仓（信号分 -2.5）
- ⏱ 时差估算：未体现的美股涨跌累计 +2.95% (±1.65%)，推算应有净值 ≈ 1.8543 [固定 beta=1，跟踪 ^NDX，滞后 2 个指数交易日]
```

---

## 一、安装

需要 Python 3.9+。依赖很轻（`requests` / `PyYAML` / `Jinja2`），不含 numpy/pandas。

```bash
git clone <你的仓库地址>
cd <仓库目录>
pip install -r requirements.txt
```

## 二、配置你的持仓

```bash
cp config/holdings.example.yaml config/holdings.yaml
# 然后编辑 config/holdings.yaml，填入你的真实基金代码、份额、成本、跟踪指数等
```

真实的 `config/holdings.yaml` 已被 `.gitignore` 忽略，不会提交，保护隐私。字段含义见示例文件里的详细注释，重点：

| 字段 | 说明 |
|---|---|
| `code` | 6 位基金代码 |
| `shares` / `cost_nav` | 份额 / 平均成本（只想看信号可都填 0） |
| `target_weight` | 目标权重（小数），填了才做再平衡提醒 |
| `is_dca` | 是否在定投 |
| `annual_fee` | 年综合费率（如 0.008） |
| `tracking.index` | **跟踪指数**：`^NDX` 纳指100 / `^GSPC` 标普500 / `^IXIC` 纳指综合 / `^DJI` 道指 / `^SOX` 费半。A 股基金留空 |
| `tracking.beta` | 敏感度，指数基金一般 `1.0`，或写 `auto` 用历史回归 |
| `tracking.lag_days` | 净值滞后的指数交易日数（多为 1~2，**建议校准**，见下文） |
| `tracking.currency_hedged` | 是否汇率对冲（多数 QDII 为 `false`） |

## 三、配置邮箱（把报告发到 QQ / 163）

**绝不要把密码写进代码或仓库**。本工具只从环境变量读邮箱配置。QQ/163 用的是**授权码**而非登录密码：

- **QQ 邮箱**：网页端 → 设置 → 账户 → 开启「POP3/SMTP 服务」→ 获取**授权码**。SMTP：`smtp.qq.com:465`。
- **163 邮箱**：网页端 → 设置 → POP3/SMTP/IMAP → 开启 SMTP → 设置**客户端授权密码**。SMTP：`smtp.163.com:465`。

本地测试（把下面的值换成你自己的；授权码不要外泄）：

```bash
export SMTP_PROVIDER=qq           # qq / 163 / 126 / gmail，会自动填 host/port
export SMTP_USER=你的QQ号@qq.com
export SMTP_PASSWORD=你的授权码
export MAIL_TO=你的QQ号@qq.com     # 收件人，多个用逗号分隔；缺省=发给自己
python -m fund_analyzer email-test   # 先发一封测试邮件，确认配置正确
```

## 四、运行方式

```bash
# 1) 跑一次真实持仓分析（联网拉数据），生成报告到 output/
python -m fund_analyzer report

# 2) 分析并发邮件
python -m fund_analyzer report --email

# 3) 只看某只基金的时差估算（联网）
python -m fund_analyzer estimate 270042 --index ^NDX --lag 2

# 4) 离线演示
python -m fund_analyzer demo
```

### 让它「每天自动」给你发邮件 —— 两种方式

**方式 A：GitHub Actions（推荐，免费、云端、无需自己开机）**

1. 把代码推到你的 GitHub 仓库。
2. 仓库 → Settings → Secrets and variables → Actions，添加 Secrets：
   - `SMTP_PROVIDER`=`qq`（或 `163`）、`SMTP_USER`、`SMTP_PASSWORD`（授权码）、`MAIL_TO`
   - `HOLDINGS_YAML`：把你 `config/holdings.yaml` 的**全部内容**粘进来（这样无需把持仓提交到仓库）
3. 工作流 `.github/workflows/daily-report.yml` 已配置好：**北京时间每个工作日早上约 7:00**
   （美股收盘后、国内净值更新前）自动跑并发邮件。也可在 Actions 页面手动点「Run workflow」立即测试。
   - 注意：GitHub 的定时任务只在**默认分支**生效。请把含本工作流的分支设为默认分支，或合并到默认分支。

**方式 B：自己的电脑/服务器 cron**

```cron
# 北京时间每个工作日 07:30 跑一次（机器时区为 Asia/Shanghai 时）
30 7 * * 1-5 cd /path/to/repo && SMTP_PROVIDER=qq SMTP_USER=... SMTP_PASSWORD=... MAIL_TO=... /usr/bin/python3 -m fund_analyzer report --email >> run.log 2>&1
```

## 五、时差估算怎么用、怎么校准

模型（详见 [docs/METHODOLOGY.md](docs/METHODOLOGY.md)）：对跟踪指数 I 的 QDII，单日估算收益

```
r_fund ≈ alpha + beta · r_index ( + r_汇率，未对冲时 ) − 日均费率
```

把「最近 `lag_days` 个指数交易日」的涨跌视为「尚未体现到最新公布净值」，逐日复利得到累计估算收益和应有净值。

**校准 lag_days（很重要，一次即可）**：找一天美股大涨/大跌，记下当天指数涨幅，再看你的基金净值是**第几天**
反映出这笔涨跌——差几个交易日，`lag_days` 就填几。`beta` 对纯指数基金填 `1.0` 即可，或填 `auto` 让程序用历史
净值对指数做回归自动估计。

**局限**：指数成分调整、汇率剧烈波动、基金现金仓位/申赎、主动管理偏离都会带来误差，**仅供参考**。

## 六、分析方法论（简版）

本工具不是「拍脑袋」，每条建议都对应公开、被广泛使用的规则：

- **估值分位定投**：用净值在近 ~2 年的分位近似估值高低；低位（<20%）倾向加大定投、高位（>80%）倾向谨慎/止盈。
- **目标止盈**：持仓收益达到目标（默认 30%）→ 提示分批止盈，落袋为安。
- **回撤止盈**：盈利后从阶段高点回撤超过阈值（默认 10%）→ 保护利润。
- **趋势/动量（辅助）**：均线多空排列、RSI 超买超卖，只做辅助、不主导。
- **再平衡**：权重偏离目标过大→把组合拉回目标配置，控制单一市场（你美股占比高）风险。
- **风险体检**：最大回撤、年化波动、夏普比率，帮助你认识每只基金的风险收益特征。

> 完整方法论、各阈值含义与参考资料见 **[docs/METHODOLOGY.md](docs/METHODOLOGY.md)**。所有阈值都能在
> `config/settings.yaml` 里按你的风险偏好调整。

## 七、目录结构

```
fund_analyzer/
  models.py        数据模型
  config.py        配置加载（settings + holdings + 邮箱环境变量）
  indicators.py    指标：均线/RSI/最大回撤/夏普/波动/分位/OLS回归
  estimate.py      ★ QDII 时差收益估算引擎
  strategy.py      策略引擎：指标 → 操作建议
  portfolio.py     组合编排：取数→指标→估算→策略→报告
  report.py        中文报告渲染（Markdown / HTML）
  emailer.py       SMTP 发送（QQ/163/126/Gmail）
  datasource/      数据源：天天基金（净值/估值）、美股指数行情（Yahoo/stooq）
  demo.py          离线演示数据
  cli.py           命令行入口
config/            holdings / settings 示例
tests/             单元测试（24 个用例）
.github/workflows/ 每日发邮件 + 测试 CI
docs/METHODOLOGY.md 方法论与模型说明
```

## 八、数据源与网络说明

- 基金净值/实时估值来自**天天基金**公开接口；美股指数/汇率来自 **Yahoo Finance**（失败自动回退 stooq）。
- 接口失败会**自动降级**（用过期缓存或跳过对应模块），不会让整个流程崩溃。
- **如果你在某些受限网络/云沙箱里运行**（比如部分主机访问不了上述站点），实时数据会取不到；
  请在能正常访问这些站点的环境运行（个人电脑、或 GitHub Actions 的云端 Runner 一般可访问）。
- 本工具仅做只读数据抓取与本地计算，不会替你下单或操作账户。

## 九、常见问题

- **QDII 限购/暂停申购**：很多美股 QDII 有大额限购。建议仍会给出，但能否买入以你平台为准。
- **节假日/汇率**：中美假期不同会让「滞后天数」当天略有偏差；未对冲基金还受汇率影响（已纳入估算）。
- **A 股基金**：净值当天/次日即更新，不做时差估算（`tracking.index` 留空即可）。
- **想改风格更激进/保守**：改 `config/settings.yaml` 里的 `strategy` 阈值即可。

## 十、测试

```bash
python -m unittest discover -s tests -v
```
