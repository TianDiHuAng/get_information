# Get_Information 情报雷达 · 现状交接文档

> 交接日期：2026-11-08 · 交接时系统状态：**全自动运行中，全部健康**
> 项目定位：每天早上 5 分钟，读完 AI 领域真正值得知道的事（不是"又一个聚合站"）

---

## 一、这个系统每天自动做什么

```
每 6 小时（watchdog 常驻循环）
  ├─ [采集] 20+ 个信息源并发抓取 → 归一化 Item（一手博客 / 榜单 / RSS / X / 国内搜索 / 羊毛）
  ├─ [清洗] URL 规范化去重 + 标题 Jaccard>0.72 合并同事件跨源
  ├─ [翻译] 非中文条目（一手/榜单/广泛）翻成简体中文，按 hash 缓存，失败保留原文
  ├─ [打分] 0.4×时效(按层半衰期) + 0.4×热度 + 0.2×层权重，AI 关键词×1.12
  ├─ [榜单] LMArena（HF 官方镜像）+ AA 智能指数（免费API）按日快照、对比昨日给 ▲▼
  ├─ [产出] site/index.html（深色可视化站，含 4 张 SVG 图 + 双榜单表）
  │         data/digest-YYYY-MM-DD.md（Markdown 日报，顶部 AI 导读）
  ├─ [归档] site/archive/YYYY-MM-DD.html + data/daily/items-YYYY-MM-DD.json（每天一份）
  └─ [推送] 每天第一轮：HTML 卡片式邮件发到 <你的收件邮箱>
  └─ [周报] 每周一 07:00 后第一轮：arXiv 新论文单独一封（只推没推过的）
```

每次 Windows 登录：启动文件夹的 `GetInfo_Watchdog.bat` 自动拉起 watchdog（采集 + Web 服务随之恢复）。

**当前实测节奏**：采集一轮约 30 秒，108 条/轮，11 源全绿。交接前一日（11-07 至 11-08）已稳定跑 4 轮，邮件、导读、榜单全部正常出稿。

---

## 二、目录与文件地图

```
Get_Information/
├── run.py                  # 一次跑完全流程（抓取→快照→渲染→日报→推送）
├── serve.py                # Web 服务，端口 8123，绑定 0.0.0.0，自带单实例探测
├── collector/
│   ├── model.py            # Item 统一模型（source/layer/title/url/heat/extra…）
│   ├── net.py              # requests 封装：重试 + 代理开关（墙外源走 socks5h://127.0.0.1:10808）
│   ├── sources.py          # 21 个源注册表（11 启用 / 10 未启用含原因）+ 各源适配器
│   ├── pipeline.py         # 并发抓取、去重、打分；关键词从 config/topics.yaml 加载
│   ├── charts.py           # 纯 SVG 图表（环形/条形/柱状/趋势折线），零外部依赖
│   ├── history.py          # 每日快照写 data/history.jsonl（同日覆盖），喂趋势图
│   ├── leaderboards.py     # 双榜单快照：fetch/update_lmarena + fetch_aa/update_aa
│   ├── health.py           # 按"抓到几条"记账（防 RSS 假活），>72h 未更新标红
│   ├── render.py           # 整页 HTML 生成（图表、双榜单、健康面板、卡片流、筛选）
│   ├── digest.py           # MD 日报 + email_html()（浅色卡片邮件模板）+ LLM 导读
│   ├── archive.py          # 每日归档：data/daily/items-日期.json + site/archive/日期.html + 目录页
│   ├── xfeed.py            # X 时间线（fxtwitter 免费镜像，无需 token）；data/x_seen.json 去重
│   ├── papers.py           # arXiv 周报：AI 制药主题（分页抓取）+ 只推没推过的
│   ├── translate.py        # 英→中翻译：仅 lang!=zh，按 hash 缓存 data/trans_cache.json，失败保留原文
│   └── pushmail.py         # QQ SMTP 推送，每天一封去重（data/mail-state.json）
├── config/
│   ├── topics.yaml         # AI 关键词表（命中即加权，可自行增删）
│   ├── x.yaml              # X 账号名单 / 每号取几条 / 点赞与字数门槛
│   ├── papers.yaml         # arXiv 周报：AI 制药主题的分类/查询式/限额 + 推送星期
│   ├── cookies.yaml        # 微博/知乎登录 Cookie（用 tools/set_cookie.py 写入，勿手抄进聊天）
│   ├── domestic.yaml       # 国内源取数方式：search(关键词搜索) / hot(全网热搜)，及关键词与每词条数
│   ├── feeds.yaml          # 额外 RSS 源（实验室/研究者/科技媒体），加源只改这里
│   ├── llm.yaml            # AI 导读：指向本机 wb_proxy 网关 glm-5.3-flash（环境变量优先）
│   ├── mail.yaml           # SMTP 授权码（已填）、收件人、daily:true=每天一封
│   └── aa.yaml             # Artificial Analysis 免费 API key（已填）
├── data/                   # 全部运行产物（gitignore 候选）
│   ├── items.json          # 本次全量条目（网站数据源）
│   ├── daily/items-*.json  # 每日全量条目快照（回溯 / 重渲染用，一天一份）
│   ├── digest-*.md         # 每日日报存档
│   ├── history.jsonl       # 每日一行统计（趋势图数据，11-07 起积累）
│   ├── lmarena.json        # LMArena Top10 快照（含 prev_rank 对比）
│   ├── aa.json             # AA 智能指数 Top10 快照（含排名/价格对比）
│   ├── health.json         # 各源健康账本
│   └── mail-state.json     # 邮件已发日期（去重）
├── site/index.html         # 【对外成品】可视化站
├── site/archive/           # 每日页面快照 YYYY-MM-DD.html + index.html 目录页（访问 /archive/）
├── logs/run.log            # 每轮采集日志（GBK 乱码是 chcp 显示问题，内容正常）
├── logs/watchdog.log       # 循环节拍日志
├── watchdog.bat            # 常驻循环（6h 一次 + 拉起 serve.py）⚠ 纯 ASCII 原因见 §六
├── tools/set_cookie.py     # 隐藏输入方式写入微博/知乎 Cookie（不经过聊天记录）
├── run_daily.bat           # 单轮采集（计划任务/手动都用它）
├── start_hidden.vbs        # 静默启动 watchdog
├── install_task_admin.bat  # 【可选】管理员运行一次：注册 08:00/20:00 计划任务 + Web 登录自启
├── docs/source-coverage.md # 21 源的通道实测结论（接新源前必读）
├── docs/roadmap.md         # 四周计划（第1/2/4周核心已全部落地）
└── research/               # 前期选型调研（Horizon/TrendRadar/RSSHub 对比）
```

---

## 三、外部依赖与凭据（都在 config/ 下，无环境变量要求）

| 依赖 | 用途 | 现状 | 失效影响 |
|---|---|---|---|
| 本机代理 `socks5h://127.0.0.1:10808`（v2rayN） | HF Papers / Google News / LMArena / HF 数据集 | ✅ 已验证 | 墙外 4 源失败，其余照常 |
| wb_proxy 网关 `127.0.0.1:8788/v1` | AI 导读 + 全站英译中（glm-5.3-flash，无需鉴权） | ✅ 正常（偶尔排队，90s 超时自动退回原文/结构化简报） | 日报少导读、英文条目保持英文，不影响采集 |
| fxtwitter 公开镜像 `api.fxtwitter.com` | X 时间线（免费，无需 token） | ✅ 走代理可用 | X 源为空，其余照常 |
| 微博/知乎 Cookie（config/cookies.yaml） | 国内热榜 | ✅ 已写入（2026-11-08 实测可抓） | 对应源自动禁用，其余照常 |
| 邮件发件（阿里企业邮箱 SMTP，587 STARTTLS） | 日报主发件（显示名「信息雷达」） | ✅ 实测可发 | 自动退回 QQ 备用通道 |
| AA 免费 key（config/aa.yaml） | AA 智能指数快照 | ✅ 实测拉取成功（1000 次/天额度） | AA 区块消失，LMArena 照常 |
| GitHub 匿名 API | 新项目榜 | ✅（60 次/时限流，够用） | GitHub 源失败 |
| Anaconda Python `D:\Anaconda\python.exe` | 全部脚本（3.11.7，pandas/pyyaml/bs4/requests 已装） | ✅ | — |

**换 LLM 服务**：改 `config/llm.yaml` 三行（api_key / base_url / model），任何 OpenAI 兼容接口都行。

---

## 四、访问入口

| 入口 | 地址 | 说明 |
|---|---|---|
| 网站（本机） | http://localhost:8123 | 常驻服务 |
| 网站（局域网手机） | http://<局域网IP>:8123 | 首次访问 Windows 弹防火墙授权，点允许 |
| 邮件日报 | <你的收件邮箱> | 每天第一轮采集后自动发，注意可能落进"订阅邮件" |
| 手动跑一轮 | `D:\Anaconda\python.exe run.py`（项目根目录） | 立即刷新网站+日报 |

页面结构自上而下：统计数字（含国外/国内条数）→ 21 源健康面板 → 4 张图表 → LMArena Top10 → AA 智能指数 Top10 → 今日必看（**只取国外**）→ 筛选按钮（全部/AI相关/国外/国内/一手/榜单/搜索/广谱）→ **「国外 · 一手与社区」卡片区** → **「国内 · 热榜与媒体」卡片区**。

分区规则在 `collector/sources.py` 的 `REGION` 字典：smol.ai / The Batch / HF Papers / HN / GitHub / arXiv / X 属于国外；B站 / 头条 / 36氪 / 少数派 / Google News(中文) 属于国内。日报邮件同样按「国外 · 今日必看 / 一手源头 / X / 论文速览」+「国内 · 热榜与媒体」排版。

---

## 五、当前运行时状态（交接快照 2026-11-08 08:00）

- watchdog：**运行中**（cmd PID 35136，11-07 19:31 启动，循环节拍正常）
- serve.py：**运行中**（pythonw PID 32796，无窗口常驻）
- 计划任务：**未注册**（非管理员注册被拒，走启动文件夹方案；如想要 08:00/20:00 固定点，右键"以管理员身份运行" `install_task_admin.bat`）
- 数据：history.jsonl 已有 11-07 / 11-08 两天 → 趋势图从今天起有折线
- 健康面板：11 源全部 fails=0
- 日志：`logs/run.log` 每轮 `exit=0`

**怎么确认系统活着**：打开网站看右上角"生成于"时间是否在 6 小时内；或 `tail logs\watchdog.log` 看最近的 tick（中文显示乱码属正常）。

---

## 六、历史坑与修复记录（改代码前必读）

1. **watchdog.bat 必须保持纯 ASCII**。cmd 按 ANSI/GBK 解析 .bat，UTF-8 中文注释的某些字节会吞掉换行符，把 `echo` 截成 `ho`，导致循环失控（tick 重复、run_daily 失联）。已重写为英文注释——**改它时别加中文**。
2. **无控制台窗口里 `timeout /t N` 会立即返回**，"6 小时"退化成 20 秒一轮，曾把 arXiv 打到 429。sleep 一律用 `powershell -NoProfile -Command "Start-Sleep -Seconds N"`。`start`/`wscript` 在无窗口环境也可能挂起，分离启动用 PowerShell `Start-Process`。
3. **Windows 下判断端口占用不能靠 bind 失败**（SO_REUSEADDR 允许重复绑定），serve.py 用的是"先 connect 探测 8123"。
4. **AA 接口的三个事实**：真实主机是 `artificialanalysis.ai`（文档写的 api.artificialanalysis.ai 是 Vercel 空壳）；鉴权头是 `x-api-key`（不是 Bearer）；完整榜单端点要 Pro，免费档用 `/free` 后缀端点。
5. **LMArena 不爬官网**（Cloudflare 403），走官方 HF 数据集 `lmarena-ai/leaderboard-dataset` 的 `text/latest-*.parquet`，每天更新。
6. **smol.ai 的 RSS 会"假活"**（返回 200 但内容停在两个月前）——这就是 health.py 按"抓到几条"记账而非看 HTTP 状态的原因。接新源一律要有最后成功时间检查。
7. 邮件 HTML 模板全部内联样式（邮箱客户端不认 `<style>` 块）；中文 HTML 邮件走 MIME `utf-8` 头，不依赖文件 charset。
8. **翻译层（translate.py）的三条约定**：只翻 `lang != "zh"` 的条目；结果按 `sha1(title||summary)` 缓存到 `data/trans_cache.json`，同文永不重翻（删缓存=次日全量重翻，会明显变慢）；模型返回必须是 JSON 数组，解析失败整批保留英文，绝不抛异常。原文留在 `extra["title_original"] / ["summary_original"]`，网站卡片有 hover tooltip。
9. 人名/仓库名（如 `mmdoctor/google-pro-helper`）会按“专有名词保留原文”的规则不翻——这是预期行为，不是漏翻。
10. **X 走 fxtwitter 的 `/2/profile/{user}/statuses`（免费、无需 token）**，走代理可用；官方 API 免费档读不了，Apify 仅作备选。噪音靠 `min_likes` / `min_chars` / `exclude_replies` 三道闸过滤。**注意转推**：`reposted_by` 与 `author.screen_name` 不同才是真转推（@ylecun 时间线 20 条里 17 条是转推），默认 `include_reposts: false` 只留原创，打开会在标题前加 `🔁 @原作者`。
11. **arXiv 周报的去重靠 `data/papers_seen.json`（按 ID，与版本号无关）**；`papers_pending.json` 是待发队列，超出 `lookback_days` 的自动丢弃。`papers_state.json` 记上次发送的 ISO 周，保证一周只发一封；错过会在下一次运行补发。
12. **arXiv 抓取必须分页**：`max_results=100` 只能覆盖约一天（cs.AI+cs.CL+cs.LG 每天 300+ 篇，关键词命中约 150/天），停机一天就永久丢。现在按 `page_size/max_pages` 翻页到 `lookback_days` 边界，每页之间 sleep 3 秒防 429。
13. **周报选题按“日期轮转”而不是取最新**：`select_items()` 把候选按发布日期分桶、各桶轮流取，避免一期全挤在最后一天。主题限额在 `papers.yaml` 的 `limit`（目前 AI 制药 35）。
14. **AI 制药主题用 `query` 覆盖而不是关键词列表**：因为要表达「生成模型家族 **AND** 分子语境」。家族覆盖 diffusion / flow matching / score-based / autoregressive / VAE / GAN / normalizing flow / generative model；单纯 OR 关键词会把纯图像 diffusion 论文全带进来（实测 144 篇噪声 vs 28 篇精准）。`topics[].query` 存在时代码直接用整条表达式。语言模型与强化学习故意**不**放进 AND 子句（会引入会计/智能体等无关论文），蛋白语言模型已由基础词 `protein language model` 覆盖。
15. **大模型 / Agent 主题已于 2026-11-08 按用户要求移除**，周报只保留「AI 制药」。以后要加回来：在 `papers.yaml` 的 `topics` 里加一项即可，代码不用改；但 `papers_pending.json` 里残留的旧主题条目要先清掉，否则会被一起选进周报。
16. **健康检查按“抓取是否成功”判定，不看条数**：X 一轮没有新推文是正常的 0 条，不能算失败（曾把 X 误标成“失败 1 次”）。`pipeline.fetch_all` 返回 `ok_sources`，`health.update` 优先用它。
17. **国内源有准入词表**：`config/topics.yaml` 的 `domestic_keywords`（AI + 科技/硬件/公司词）。国内条目必须命中其一才收，否则头条/B站的社会新闻会灌满国内区。实测 96 条 → 73 条。词表是正则子串匹配，英文词按单词边界，中文按包含。
18. **微博/知乎走 Cookie**：`config/cookies.yaml` 由 `tools/set_cookie.py` 写入（隐藏输入）；为空时对应源自动禁用，健康面板显示“需 Cookie”。微博端点 `weibo.com/ajax/side/hotSearch`，知乎解析 `zhihu.com/hot` 里的 `js-initialData`。
19. **热榜要“多抓再筛”**：头条/微博/知乎的榜单前 15 条几乎全是社会新闻，撑不起科技区。头条抓 50 条、B站 30 条，再让 `domestic_keywords` 过滤。
20. **微博/知乎已改为关键词搜索（2026-11-08）**：`config/domestic.yaml` 里 `mode: search`，关键词 AI / 大模型 / 人工智能 / 芯片 / 机器人，每词 3 条。微博走 `s.weibo.com/weibo?q=`（HTML，`node-type="feed_list_content"`；没有状态链接时用 `mid` 拼 `m.weibo.cn/detail/{mid}`），知乎走 `api/v4/search_v3`（跳过 `ai_zhida`/广告，只留 `search_result` 里的 answer/article）。
21. **一手源扩展在 `config/feeds.yaml`**（10 个实验室/研究者 + IT之家），加源不改代码。实测直连/代理都不通的：OpenAI、Anthropic、Meta、HF Blog、Qwen 博客、BAIR、NVIDIA、量子位、机器之心——别硬加，要接得走 RSSHub 或镜像。
22. **羊毛福利**：`deals` 源用 Google News 搜「免费额度 / 免费 API / 免费 GPU 算力 / free AI credits + when:7d」，再做标题黑白名单（剔掉"下载/在线观看/破解"和"收费/涨价"类反向新闻）；全站条目命中 `deal_keywords` 也会打「羊毛」标。什么值得买的 `/feed` 返回 HTML 不是 RSS，已移除。
23. **X 也有免费关键词搜索，但不可靠**：`api.fxtwitter.com/2/search?q=...&feed=latest` 可用（返回结构与时间线一致），但**限流很凶**（连续 3-4 个查询就开始回 404）、且返回 404 也代表"无结果"，无法区分。现在每轮只轮换跑 2 个关键词（`x_search_state.json` 记 offset），结果打 🔎 标、按点赞取前 25。
24. **Apify 已接入（2026-11-08）**：token 在 `config/secrets.yaml`（`tools/set_secret.py apify|apify2|apify3` 写入），支持**多账号轮换**（`apify_token/_2/_3`，每个免费号 $5/月）：某个号整批 `noResults` 或报错就自动换下一个。actor 默认 `apidojo~tweet-scraper`（$0.0001/条，$5≈5 万条）。`collector/apify_x.py` 负责搜索；`sources._x_fetch_all()` 策略：**Apify 有结果就用 Apify，否则退回 fxtwitter 免费搜索**。apidojo 偶发整批 `noResults`（actor 侧被 X 限流），此时自动走免费通道。
25. **Telegram 公开频道可以抓（2026-11-08 实测）**：`https://t.me/s/<channel>` 走代理返回 200，页面里 `.tgme_widget_message_text` 是正文，`data-post` 是消息链接，`<time datetime>` 是时间。已接 `config/telegram.yaml`（默认 `zaihuapd` 在花盘点），归到国内区。私密频道拿不到；不开代理必失败。
26. **OSS Insight 的 trending 榜已死，不是墙**：`/v1/trends/repos/` 和 `/v1/collections/hot/` 都返回 `data_quality.status=unavailable`，自 2026-03-01 起其 GitHub 事件采集跌到基线 0.3%。官方建议改用 `/gh/repos/{owner}/{repo}` 取总量。结论：trending 用 GitHub Search API 自己算，别依赖它。

---

## 七、维护纪律（来自 roadmap，仍然有效）

1. **源到 30 个就停**——再加只会稀释信噪比。
2. **每周看一次健康面板**：连续标红的源直接删，不要"以后修"。
3. 日报每源最多 2 条、总数封顶 20 条（`digest.py` 的 `_pick` 已实现）。
4. 先用一周数据回答"哪 3 个源贡献了 80% 必看条目"，再决定加什么。

---

## 八、未完成事项（按优先级）

| 事项 | 状态 | 缺什么 |
|---|---|---|
| 08:00/20:00 固定计划任务 | 脚本已就绪 | 用户以管理员跑一次 `install_task_admin.bat` |
| alphaXiv | 暂缓 | 本机网络时通时断（代理也不通），不值得硬啃 |
| 微博/知乎热榜 | ✅ 已接（2026-11-08） | Cookie 会过期，失效后重跑 `tools/set_cookie.py` |
| X/Twitter | ✅ 已接（免费） | 想加人改 `config/x.yaml`；需要关键词搜索才要 Apify |
| arXiv 周报（AI 制药） | ✅ 已接（每周一） | 改 `config/papers.yaml` 的查询式/限额 |
| 线上部署 | 未做 | 现为局域网；要外网随时看，把 site/ 部署到静态托管（每次采集后重传即可） |
| 源失败告警 | 未接 | health 数据已就绪，在 run.py 里加"fails≥3 时调 pushmail"即可 |
| 历史归档 site/archive/ | ✅ 已完成（11-08 起） | 旧日期（11-06/11-07）只有日报 MD，无条目快照 |

---

## 九、快速验证清单（接手后跑一遍）

```bat
cd /d D:\AI\project\Get_Information

:: 1. 手动跑一轮（约 30 秒，应看到 11 个源全 ✓ 和 推送/日报路径输出）
D:\Anaconda\python.exe run.py

:: 2. 网站
curl -s -o nul -w "%{http_code}" http://localhost:8123/    :: 应输出 200

:: 3. 循环节拍（应看到最近的 tick，且间隔约 6 小时）
type logs\watchdog.log

:: 4. 双榜单快照存在
type data\lmarena.json | findstr date
type data\aa.json | findstr date
```

全过 = 系统完好。任何一步失败，优先看 `logs/run.log` 最后 50 行的报错段。
