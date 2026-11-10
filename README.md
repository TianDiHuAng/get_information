# Get_Information · 信息雷达

每天自动采集 AI 前沿信息（一手博客 / 论文 / X / Telegram / 国内科技媒体 / 羊毛福利），
去重、判断、打分后生成一个本地可视化站点 + 每日邮件日报，每周一份 arXiv（AI 制药）周报。

## 功能

- **多源采集**：28 个源（实验室博客、arXiv、HF Papers、HN、GitHub、X、Telegram、微博、知乎、36氪、IT之家…）
- **中文阅读**：非中文条目自动翻译成简体中文（带缓存）
- **补正文与日期**：对够格条目抓原文页（评分不再只看 RSS 摘要），并补回发布时间
  —— 知乎/微博之前把时间丢掉了，导致旧文被当成新料
- **注意力评分**：LLM 按「五轴 × 内容类型权重」独立打两次分，按信源分层过门槛；
  模型不可用时自动退回关键词/时效打分，**任何情况下都不阻断出刊**
- **跨天去重**：每个条目有稳定身份（arXiv 的 abs/pdf、微博 m 站与主站会合并），
  记 `first_seen / last_seen`，最近 7 天进过日报的不再出现
- **事件聚簇**：不同来源报道的同一件事收成一个事件，日报只出代表稿（官方一手 > 有全文 > 高分 > 早发），
  并标出「N 篇 / N 家」；事件热度按独立参与方算（48h 窗口、24h 半衰期）
- **结构化**：分类 / 标签 / 主体公司 / 是不是一条具体新闻，喂主题页、事件与日报
- **防幻觉**：导读里出现的公司名与数字必须能在原文找到，否则整段丢弃（`grounding`）
- **三块产出**：网站（国外 / 国内分区）、每日邮件日报、每周论文周报
- **日报按规则编排**：头条 → 3 条看点 → 正文 → 快讯，一件事一条、单源最多 2 条，
  **不调模型**（模型只写导读，且要过防幻觉校验）；同一批内容换个抓取顺序排出同一期
- **告警**：源连续失败/长期静默、日报缺期、预算耗尽、失败率偏高，同一天同一条只发一次信
- **成本可控**：每次 LLM 调用留回执，同输入零成本复用；有每日/每小时预算上限；可换备用模型
- **单文件离线归档**：`site/offline.html` —— 今日要闻 + 本周要闻 + 主题分布 + 时间线，
  一个文件、不引用任何外部资源，断网也能看
- **分享图**：每次跑生成 `site/og.png`（1200×630），转发到微信/Telegram/X 时有预览；
  各页面带 `og:` / `twitter:` 标签
- **周报月报**：从日报汇编（不调模型）—— 周报取 20 件、月报 30 件，
  按"报道面 + 持续天数 + 分数"排序，持续在说的话题排在一次性刷屏之前；
  输出 `data/weekly-<日期>.md` / `data/monthly-<日期>.md`
- **主题页**：`/topics.html` —— 分类与标签可点可翻，每个分类/标签一页历史
- **长期时间线**：`/timeline.html` —— 主体 × 月份的跨度（跨 120 天），
  以及同一事件在**官方 / 媒体 / 社区**三种渠道下的说法并列
- **运行看板**：`/board.html` —— 源健康、评分分布、模型成本、告警，以及
  **官方发布 vs 国内讨论**的双轴对照（今天唯一重合的主体是谁）
- **可校准**：`tools/make_gold.py` + `tools/eval_selection.py`，用自己的金标算准确率/覆盖率，
  并把门槛从 40 扫到 90 看每一档的准召
- **个性化**：卡片上点 👍/👎，下一轮排序会微调（默认 ±8%，只调排序、不碰入选门槛）
- **突发即时推**：官方一手 + 分数 ≥85 + 12 小时内 → 立刻推（邮件 / Telegram / webhook），
  23:00–08:00 免打扰
- **多出口**：除了网页和邮件，还生成 `feed.xml`（今日要闻）/ `feed-all.xml` / 按分类的 feed、
  `api/v1/latest.json`（带五轴与理由）、`llms.txt` —— 给 RSS 阅读器和 Agent 读
- **本地存储**：SQLite（`data/radar.db`）+ 产物文件，全部在 `data/`

## 快速开始

```bash
# 1) 依赖
pip install -r requirements.txt

# 2) 准备配置（example → 真实文件，填自己的 key）
cp config/llm.example.yaml     config/llm.yaml
cp config/mail.example.yaml    config/mail.yaml
cp config/secrets.example.yaml config/secrets.yaml
cp config/cookies.example.yaml config/cookies.yaml
cp config/aa.example.yaml      config/aa.yaml

# 3) 跑一轮
python run.py            # 完整一轮（含 LLM 评分）
python run.py --skip-rate  # 跳过 LLM 评分：断网或只想调样式时用
python run.py --no-mail    # 不发日报邮件（首次试跑推荐）
python run.py --dry-push   # 不发告警与突发推送（只看不发）
python run.py --fresh      # 忽略断点状态，强制重新抓取

# 4) 看站点
python serve.py        # http://localhost:8123
```

**断点续跑**：抓取完成后会写 `data/state-<日期>.json`。中途失败重跑时会跳过抓取与补正文，
直接接上后面的阶段（模型调用有回执保护，重跑不花钱）。状态超过 12 小时自动作废，跑完即删。

定时：`watchdog.bat`（Windows）每天 09:00 跑一次，并发送日报。

测试：`pip install -r requirements-dev.txt && python -m pytest tests -q`
（测试不联网、不花钱：LLM 全部用假的，数据库一律在临时目录）

标定"选得准不准"：

```bash
python tools/make_gold.py --n 120        # 从今天的 items.json 挑难例，生成 data/gold.jsonl
# 或者在后台「标注」标签里点按钮标（写同一个文件）
python tools/eval_selection.py --enrich --split development   # 调提示词时只看开发集
python tools/eval_selection.py --enrich --split holdout       # 改完用留出集验收
python tools/eval_selection.py --enrich --models a,b          # 多模型并排比较
```

金标每行带三组字段：`material`（喂模型的材料）、`sourceFacts`（tier / 一手 / 语言，决定门槛）、
`samplingContext`（开发集或留出集、分层，决定怎么拆错例），外加 `gold.decision`。
**留出集只在最后用一次** —— 反复看同一批样本调提示词，会把它调成只会做这几道题。

另外还有归组评测（关系判断）：

```bash
python tools/make_relation_gold.py       # 从已判过的关系对里挑样本，生成 data/relation-gold.jsonl
# 手工把 gold.relation 改成 SAME_OCCURRENCE / SAME_STORY / UNRELATED / ROUNDUP
python tools/eval_relations.py           # 出 4×4 混淆表、每类 F1、置信度门槛曲线
```

## 一条条目的流程

```
采集(28 源) → 身份去重 → 老分(时效/热度/层权重) → 补正文与日期 → 重算分 → 落库(指纹/修订)
   → 预筛(LLM) → 五轴 × 2 次(LLM) → 分等级门槛 → 排序分
   → 结构化(分类/标签/主体) → 事件聚簇(粗排 → 关系判定 → 复核) → 热度 → 翻译
   → 规则编排成刊(头条/看点/正文/快讯) → 导读(LLM + grounding 校验) → 告警
   → 出口：网站 / 日报 / RSS / JSON API / llms.txt
```

事件聚簇的成本控制：先用 IDF 加权的 token 重合粗排，只把够像的对送进模型；
判定结果落 `event_pairs`，同一对永不重复付费。实测 215 条 → 24 次判定 → 9 个多篇事件。

两个分怎么用：

| 分 | 是什么 | 用在哪 |
|---|---|---|
| `attention.score` | 五轴加权（0–100），判断「值不值得看」 | 精选门槛、日报取舍 |
| `extra.score` | `0.8 × attention + 0.2 × 老分` | 站点排序（时效只剩轻微修正） |

## 站点结构

结构对齐 AIHOT 的公开站（`精选 / 全部 / 热门 / 文章页 / 事件页 / 日报 / 周报 / 月报 / 主题 / 搜索 / 关于 / 条款 / 隐私 / 更新日志 / Agent`），
视觉是本项目自己的「纸感编辑风」（暖纸底 + 衬线标题 + 琥珀强调，跟随系统深色模式）。

```
/                精选（卡片点进站内文章页）
/all.html        全部动态，20 条一页，/all/2.html …
/hot.html        热门：按事件热度排
/items/<id>.html 文章页：评分理由 + 五轴 + 正文摘录 + 同事件其他报道 + 👍/👎/☆
/events.html     事件榜 + /events/<id>.html（官方 / 媒体 / 社区 三种说法并列）
/daily.html      日报期号 + /daily/<日期>.html
/weekly.html     周报 + /weekly/<日期>.html
/monthly.html    月报 + /monthly/<日期>.html
/topics.html     主题总览 + /topics/<分类或标签>.html
/timeline.html   主体 × 月份跨度
/search.html     纯前端搜索（当天条目全嵌在页面里）
/board.html      运行看板
/admin.html      后台：运行 / 信源（可停用、可试抓）/ 内容诊断 / 评测 / 模型调用 / 配置 / 告警
                 访问需要口令，见下；除"停用源"与"试抓"外都是只读
/agent.html      给 Agent 用：RSS / JSON / llms.txt 的接入说明
/starred.html    我的收藏（localStorage，只在本机）
/feedback.html   反馈机制说明 + 当前学到的权重
/about.html /terms.html /privacy.html /changelog.html /more.html
/offline.html    单文件离线归档（断网可看）
/archive/        历史归档
feed.xml · feed-all.xml · feed/category/*.xml · api/v1/latest.json · llms.txt · og.png
```

顶部导航贯通全部页面，手机端有固定底栏。每个页面都自带样式，不依赖外部资源。

**后台**：`python serve.py` 启动时会在控制台打印后台口令（也存在 `data/admin_token.txt`，
该目录不进 Git）。打开 `/admin.html` 输入口令即可。

后台能做三件事，其余都是只读：

- **停用 / 启用信源**：只写 SQLite 的开关，下一轮抓取跳过它；不改代码里的源定义。
- **试抓**：真的跑一次这个源的抓取器，**不入库**；慢源（X 的 Apify）会如实返回超时。
- **标注**（`?tab=better`）：给今天的条目打「选 / 不选 / 两可」，写进 `data/gold.jsonl`。
  和你用编辑器改那个文件完全等价 —— 不碰提示词、不碰门槛。
  顶部可切「标进开发集 / 留出集」；标完跑 `python tools/eval_selection.py --enrich --split development`。
- **评测对照**（`?tab=evals`）：点开一份 `data/eval/*.json`，按模型并排看指标，
  再按「判错 / 判对 / 失败 / 只看分歧 / 分层」逐条看模型给了什么理由。

改门槛、预算、提示词仍然改 `config/*.yaml`，下一轮自动生效。

## 换成你的行业

这个站默认是「AI 行业」。换成别的行业**不用改代码**，改 `industry/` 下的一套配置就行：

```bash
python tools/customize.py new legal --name "法律热点"   # 建行业包骨架
python tools/customize.py use legal                      # 切过去
python tools/customize.py check                          # 体检：找出所有"改了一半"的地方
```

行业包由这几部分组成（`industry/<slug>/` 覆盖 `config/` 同名文件，原来的始终保留）：

| 文件 | 管什么 |
|---|---|
| `taxonomy.yaml` | 分类、标签、实体（公司/机构）、免核对词 |
| `topics.yaml` | 主题页目录 |
| `wording.yaml` | 改用词：读者不用的行话、营销词（空表 = 零调用） |
| `prompts/*.md` | 判断标准：预筛、五维评分、结构化、事件归组 |
| `config/industry.yaml` | 站名、slogan、出刊时间、三档门槛 |
| `config/sources.yaml` | 信源分级（T1/T1_5/T2）与参与方式（editorial/hot_signal/isolated） |

完整步骤见 **[docs/customize.md](docs/customize.md)**，包括门槛怎么重新校准、
哪些字段上线后不能改、`check` 每条告警是什么意思。

## MCP（给 Agent 直接调用）

```bash
python mcp_server.py        # stdio，一行一个 JSON-RPC
```

挂到 Claude Desktop / Cursor：

```json
{"mcpServers": {"zbit": {"command": "python", "args": ["D:/AI/project/Get_Information/mcp_server.py"]}}}
```

七个工具，工具名 = `<前缀>_<能力>`（前缀在 `config/industry.yaml` 的 `mcp_prefix`）：

| 工具 | 做什么 |
|---|---|
| `zbit_get_latest` | 今天精选的条目，带评分与推荐理由 |
| `zbit_search` | 按关键词搜最近 14 天 |
| `zbit_get_hot_topics` | 按热度排序的事件榜 |
| `zbit_get_story` | 一个事件的详情（官方 / 媒体 / 社区） |
| `zbit_get_daily` / `_weekly` / `_monthly` | 日报 / 周报 / 月报全文 |

只读、不调模型、不写库；读的是公开读取层（旧文与无日期已被挡掉）。

## 安全阀

调页面、改样式、跑测试时，不该抓真实网络、烧模型钱、往群里推消息。三个环境变量：

| 变量 | 默认 | 关掉之后 |
|---|---|---|
| `RADAR_COLLECT` | 开 | 不抓网络，流水线其余阶段照跑（页面用旧数据） |
| `RADAR_MODEL` | 开 | 不调模型，评分/结构化/翻译静默降级 |
| `RADAR_PUSH` | **关** | 不发邮件、不推告警、不推突发 |

```bash
RADAR_PUSH=1 python run.py          # 显式打开推送（默认是关的）
RADAR_COLLECT=0 RADAR_MODEL=0 python run.py   # 只重建页面，不抓不花钱
```

它们**只决定"发不发出去"**，不决定走哪套逻辑 —— 关掉采集不会改变评分规则，
关掉模型不会改变筛选口径。

## 配置说明

| 文件 | 作用 |
|---|---|
| `config/feeds.yaml` | 额外 RSS 源，加源只改这里 |
| `config/x.yaml` | X 账号名单 + 关键词搜索矩阵 |
| `config/telegram.yaml` | Telegram 公开频道 |
| `config/domestic.yaml` | 微博/知乎：热搜 or 关键词搜索 |
| `config/topics.yaml` | AI 关键词 / 国内准入词 / 羊毛词 |
| `config/scoring.yaml` | **评分口径**：五轴权重矩阵、分层门槛、双次、混合比例 |
| `config/events.yaml` | **聚簇口径**：召回窗口、粗排门槛、一轮最多判几对、复核线、热度参数 |
| `config/structure.yaml` | **结构化口径**：每轮最多抽几条、并发数 |
| `config/extract.yaml` | **正文口径**：抓多少篇、正文最短长度、哪些站不抓（JS 页面/登录墙） |
| `config/prefs.yaml` | **个性化口径**：各种动作的权重、微调幅度、证据门槛 |
| `config/push.yaml` | **推送口径**：通道开关、突发门槛、官方域名、免打扰时段 |
| `config/taxonomy.yaml` | **词表**：分类、标签、实体别名、grounding 豁免词 |
| `config/prompts/*.md` | **提示词**：预筛、注意力评分、结构化、两两关系、复核（改完即时生效，版本按内容哈希） |
| `config/papers.yaml` | arXiv 周报主题与限额 |
| `config/mail.yaml` | 邮件服务与收件人 |
| `config/secrets.yaml` | **所有 token / 密码（已 gitignore）** |

调口味不用改代码：权重在 `scoring.yaml`，判断标准在 `prompts/`。
改了提示词，版本号（内容哈希）自动变化，旧回执不会污染新结果。

## ⚠️ 安全

`config/secrets.yaml`、`config/cookies.yaml`、`config/mail.yaml`、`config/aa.yaml`、`config/llm.yaml`
以及 `data/`、`logs/`、`site/` 都在 `.gitignore` 里，**不要提交**。

提交前可跑一次自检：

```bash
python tools/scan_secrets.py
```

## 目录

```
collector/     采集/清洗/判断/打分/渲染/推送
  identity.py  条目身份：URL 规范化、平台原生 ID、标题相似度
  extract.py   正文与日期：抓原文页、语义容器选正文、三级日期回退
  store.py     SQLite：跨天去重、已报抑制、评分留痕、事件、LLM 回执、运行阶段
  llm.py       统一 LLM 调用：回执、预算、重试、换模型、结构化解析
  rating.py    注意力评分：预筛 → 五轴 × 2 → 门槛 → 降级
  events.py    事件聚簇：粗排召回 → 四类关系 → 复核 → 合并 → 热度
  structure.py 结构化：分类 / 标签 / 主体 / 是不是一条具体新闻
  grounding.py 防幻觉：专名与数字必须能在原文找到
  edition.py   成刊：规则编排头条/看点/正文/快讯（不调模型）
  prefs.py     个性化：反馈 → 词级权重 → 排序微调
  breaking.py  突发：够格立刻推（免打扰、永久去重）
  push.py      通道：邮件 / Telegram / webhook
  export.py    多出口：RSS / JSON API / llms.txt
  evaluate.py  评测：准确率/覆盖率/门槛扫描（配 tools/ 下两个脚本）
  board.py     看板：源健康 / 评分分布 / 成本 / 官方 vs 国内舆论场
  timeline.py  时间线：主体 × 月份跨度 + 官方/媒体/社区说法对比
  topics.py    主题页：分类与标签的历史列表
  report.py    周报月报：从日报汇编（规则编排）
  share.py     分享图：1200×630 的头条卡片 + og/分享元信息
  alerts.py    告警：源健康、缺期、预算、失败率
config/        配置（含 example 模板、评分口径、提示词）
data/          运行产物（忽略）
site/          生成的网站（忽略）
tests/         单元测试（不联网）
tools/         辅助脚本（cookie/token 写入、密钥扫描）
docs/          交接、源覆盖、AIHOT 分析与吸收路线
```
