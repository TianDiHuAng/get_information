# AIHOT 拆解：它怎么做的，以及能给「信息雷达」什么

> 分析对象：https://github.com/KKKKhazix/AIHOT （MIT，与 aihot.news 线上站同一份引擎代码）
> 方法：全仓通读（706 文件 / 418 个 `.ts` / 75 个 `.sql` / 190+ 测试文件），重点读 `docs/`、`industry/`、`packages/backend/src/{sources,editorial,events,publication,reports,providers,jobs}`；同时实测本项目的 `data/` 产物做对照。
> 注：仓库是单次 squash 提交（"同步引擎"），看不到演进历史，只能看结果形态。

---

## 0. 先说三个结论

1. **它是一个"注意力筛选器"，不是一个"信息聚合器"。** 采集只是入口；真正的资产是"怎么判断一条消息值不值得看"——这部分被写成了可评测、可校准、可换行业的东西。
2. **你的流水线骨架是对的，缺的是中间那层"判断"。** 你现在真正决定排序的是「多新 + 多热」，"是不是 AI 的事"只值 **12%** 的加成。
3. **有几个立刻能量化的硬伤**（实测，见 §1.3）：站点列表四成是昨天的同位条目；同一期日报里同一事件出现两次（LG 的 K-EXAONE 2.5，汽车之家 + Unite.AI）。前者是"没有跨天记忆"，后者是"没有事件聚簇"。

---

## 1. 你的现状（实测，作为对照基线）

### 1.1 结构与体量
- 4,635 行 Python，21 个 collector 模块；单进程直线跑：`pipeline.run()` → `translate_items()` → `update_health()` → `append_history()` → 写 `items.json` → `render()` → `archive.save()` → `digest.build()` → `send_mail()` → `papers.run()`（`run.py:27-55`）。
- **只有 `send_mail` 和 `papers` 被 try 包住**。`pipeline.run()` 抛异常，整轮连站点都不生成。
- 存储**不是 SQLite**：全仓 0 处 `sqlite3`，实际是 12+ 个 JSON 文件（`items.json`、`daily/*.json`、`trans_cache.json`、`health.json`、`history.jsonl`、各种 `*_seen.json`）。**README 第 12 行"SQLite 无依赖"与实际不符**，建议改掉或真的换成 SQLite。

### 1.2 关键实现
| 环节 | 现状 |
|---|---|
| 采集 | `ThreadPoolExecutor(8)`，28 个源；`SOURCE_TIMEOUT` 字典**实际无效**——`as_completed` 返回后 `fut.result(timeout=…)` 立即返回，单源卡住会拖住整轮（`pipeline.py:118,129-132`） |
| 去重 | URL 规范化 + 标题 bigram Jaccard > 0.72 贪心合并；O(n²)、顺序敏感、只比标题（`pipeline.py:144-168`） |
| 打分 | `100×(0.4×时效 + 0.4×热度 + 0.2×层权重)`，关键词命中 ×1.12；热度按**源内** `log1p` 归一（`pipeline.py:171-197`） |
| LLM | 两处：翻译（batch 6、temp 0.1）+ 日报导语（全局 1 次、取前 20 条）；无 failover、无重试、无预算 |
| 缓存 | `sha1(title‖summary)` → `data/trans_cache.json`（170KB，只增不淘汰，整文件读写） |
| 产出 | 单页 f-string 拼 HTML，254KB / 215 张卡全量内联；无 API / RSS / JSON 出口 |

### 1.3 两个实测硬伤（可直接复查）

**① 站点列表没有跨天记忆**
```
data/daily/items-2026-11-09.json  184 条 → 其中 80 条(43%) URL 与 11-08 完全相同
data/daily/items-2026-11-10.json  215 条 → 其中 89 条(41%) URL 与 11-09 完全相同
```
落到日报（读者真正看的那份）是 4/24：`11-10` 的 24 个链接里 4 个与 `11-09` 完全相同，
全部来自 arXiv 与 Google News —— 这两类源本身会连续多天返回同一批条目，而项目没有已报抑制。

**② 同一期日报里，同一件事出现两次**
`digest-2026-11-10.md` 里 LG 的 K-EXAONE 2.5 出现了两次：
「LG免费开放K-EXAONE2.5模型API - 汽车之家」与「LG AI Research 开放 K-EXAONE 2.5 模型免费 API 访问 - Unite.AI」。
两条标题的 bigram 相似度只有 0.50，低于 0.72 合并线——**光比标题永远解决不了这个问题**，
必须靠事件级聚簇（§3 的 ④）。

注意：这两条不是同一个 URL，所以在 `items.json` 层面也是两条。这解释了为什么"去重"看起来在工作，
日报里却还是重复。

### 1.4 其他可见缺口
- 无队列、无断点：任何一步失败整轮作废，产物每轮覆盖。
- 无测试、无依赖清单（无 `requirements.txt` / `pyproject.toml`）。
- 无告警：源失败只 `print`，`handover.md §八` 自己写着"源失败告警 未接"。
- 未归一跨 host（`m.weibo.cn` 与 `weibo.com` 视为两篇）；215 条里 43 条没有发布时间（强制按 48h 算）。

---

## 2. AIHOT 是怎么做的

### 2.1 形态
- **三进程**：`api`（Fastify，只做读接口与对外出口）/ `worker`（pg-boss 队列 + 定时）/ `web`（React Router SSR，**只走 HTTP 读 api，不碰数据库**）。
- **业务代码 21,299 行**在 `packages/backend/src`，16 个领域目录；PostgreSQL 17 + 75 个迁移；Node 24 直跑 TS，后端无构建步骤。
- **最关键的架构决定**：代码里没有一行"AI 行业"的知识。行业知识全在 `industry/`（提示词、门槛、分类、主题、示范信源），站点身份全在 `site/`（站名、文案、品牌、每一步用哪个模型）。所以别人 clone 后只改这两个文件夹就能变成"法律热点站"——**这就是它敢开源的全部理由**。

### 2.2 一条资料走完的路
```
采集(6类源) → 判重入库 → 预筛 → 双次评分 → 结构化 ──┬→ 写作 → 归组(聚簇+复核) → 热度 → 成刊 → 多出口
                                        (并行)      │
                                                    └→ 发布闸门(同一条新闻只占一个席位)
```

### 2.3 六类信源收敛成一个契约
`Candidate` 契约 + `bodyStatus: pending|ok|none` 决定后续是否再抓正文（`sources/types.ts:6,24,48`）。每种 kind 有**独立配置白名单**（`sources/config-keys.ts`）：填了不认识的键，**保存被拒绝、抓取直接失败并在后台显示原因**，绝不静默退回通用解析。

- X：只对 `publisherRole` 为 organization/person 的账号拉自线程，剔转推再去重；X Article 的 blocks 还原成标题/列表/图片；视频选 ≤832kbps 档。
- 微信：每账号每 10 分钟一次列表、每次 ≤8 篇、首查只收 7 天内、正文失败重试 3 次/3 天。
- 网页列表：Jina Markdown 与 cheerio 双路解析，导航/登录/年份归档一律剔除。

### 2.4 抓取频率由"产出"反推
- `interval = 24*60/(perDay*3)`，夹在 `[15, 60]` 分钟；X 与付费 Jina 地板 120；`hot_signal` 源 180；`PAID_LISTING_FLOOR = 60`（`collect.ts:566-592`）。
- 条件请求：`{configHash, etag, lastModified, responseUrl}`，304 只在**同一 responseUrl** 且详情页无 pending 时接受。
- 失败：`fail_count+1`，5 连败转 `failing`，`next_fetch = LEAST(interval*(n+2), 360)` 分钟；预算耗尽**不算失败**（15 分钟后重来）。
- 并发按步骤分级：fetch 8 / X 分片 2 / 微信 2 / analyze 6 / extract 4 / **group 1（串行建事实）** / digest 3。

### 2.5 预筛 → 双次评分 → 分等级门槛
| 环节 | 实现 |
|---|---|
| 预筛 | `prefilter.md`：PASS/BLOCK/UNKNOWN，**只有 BLOCK 出局**，UNKNOWN 等材料补齐（宽召回） |
| 评分 | `selection-score.md`：7 类内容 × 5 轴权重矩阵（每行和=10）→ 0–100 |
| 双次 | `SCORE_CALLS = 2`，**串行**（注释写明是为复用 provider 的 prompt cache），和 ≥ 2×门槛，展示 `floor(sum/2)` |
| 门槛 | `T1:60 / T1_5:65 / T2:76`，类别下限 `ecosystem:70 / leaderboard:76`，**只抬不降** |
| 写作分档 | 均分 > `understandFloor(50)` 走贵的内容理解，否则走便宜的标题摘要 |
| 发布闸门 | `selected = 可入选 && grouping_status==='complete' && selection_adds_value!==false` |
| 席位 | seat 建在 **fact** 而非 story 上，`settleSeats` 只让代表占位：`T1 → 官方账号 → 有全文 → 高分 → 最早` |

**评分提示词的三个设计要点**（这是最值得抄的部分）：
1. **五轴**：`sig` 实质份量、`nov` 信息增量、`cred` 证据强度、`reson` 共振面、`act` 可用性；每轴都写明"不要重复计算什么"。
2. **输入故意不含**信源分级、站名门槛、旧分数——模型只判"这件事值多少注意力"，门槛留在代码里。
3. **噪声写死硬上限**：客户案例 `sig≤4`、例行小版本 `sig≤3`、营销软文 `sig≤2`、只有预告 `nov≤3 且 cred≤4`、打包早报 `sig≤3`、单基准刷分 `sig≤4 且 reson≤3`。

### 2.6 去重三层 + 身份
| 层 | 手段 |
|---|---|
| 身份 | `normalizeUrl`（强制 https、去 www/fragment/追踪参数、query 排序）；X 状态 → `x:<id>`；兜底 `src:<source>:sha256(url\1title)`；**唯一键 + ON CONFLICT DO NOTHING**，他源命中只记 `article_discoveries`，不覆盖原标题摘要 |
| 内容指纹 | `sha256(title\1body\1excerpt)`；历史版本命中即"非新料"（含 U+FFFD 传输丢字容错） |
| 事件聚簇 | **不用 pgvector**：`real[]` 存 1024 维向量，进程内余弦，只扫近 14 天窗口；无 key 时退回字符 bigram（阈值 0.25） |

聚簇阈值（按形态分叉）：报告 0.6 / Top10；帖子 0.72、0.92 免判、peer 0.78。判定四值 `SAME_OCCURRENCE / SAME_STORY / UNRELATED / ROUNDUP`；**相似度 < 0.85 的合并必须第二模型确认**，两故事合并需两模型一致且门槛 0.75。

> **跨源"同一新闻"不靠标题指纹，靠 fact 归组**——这句话是它和你的 `Jaccard>0.72` 的根本差别。

### 2.7 热度：按事件、按独立参与方
```ts
HOT_RULE_VERSION = "heat-v1-48h-halflife24h"
HEAT_WINDOW_HOURS = 48; HALF_LIFE_HOURS = 24; MIN_PARTICIPANTS = 2
heat = Σ 0.5^(Δt/24h)   // 每个参与者只取最新一次
// 需 ≥2 个参与者，且其中 ≥1 个编辑源
```
- **参与方是谁可以配**：dev.to/HN 的作者、自媒体矩阵（`signal_group`）、公司自有渠道（`owner_entity_id`），否则是信源本身。这是防矩阵号刷榜的关键。
- **诚实的趋势**：趋势只比"两次窗口都完整可观测"的参与者；抓取滞后（3 个间隔或 90 分钟没成功）的信源被剔出对比组，所以趋势可能是 `unknown` 而不是假装有数。
- badge：`surge` = 近 6h ≥3 源且占比 ≥50%；`rising` = 涨幅 >15%。
- 榜单**落库**（`hot_rankings` + `rule_version`），公开读取前**重新校验**可见性：存的是快照，不是真相。

### 2.8 花钱的请求有回执
- 唯一入口 `chatJson` → `paidRequest`；逻辑键 `service:purpose:model:sha256(identity):attemptTag`，identity 含 promptVersion + system/user 哈希 + 温度 + maxTokens → **同输入零成本复用**。
- 调用前先落"占位行 + attempt 行"；原始响应**先存库再写业务**；进程崩了恢复时复用已付费结果。
- **失败分 8 类**（off / budget / busy / outage / unknown / refused / unusable / other）；`unknown` **绝不自动重发**，30 分钟后 `ops.recover` 放行一次，再不明等管理员。
- failover **只切"评测过的备份"**（不同 service 且声明 `fallbackFor`）：有备份 30s 超时，无备份 120s。
- 熔断：5 分钟窗口 10 次不可用 → 断 5 分钟 + 单探针。
- 预算三档：llm `300/min, 6000/h, 40000/day`；jina `5/50/300`；socialdata `10/100/1000`；用 `pg_advisory_xact_lock` 串行化计数。

### 2.9 队列与恢复
- pg-boss on PostgreSQL，10 个队列各自声明 retry/expire；`singletonKey` 防重复入队；入队与业务写同事务。
- 心跳：worker 每分钟写 `settings.heartbeat.worker`，api 侧 30 分钟无心跳告警。
- 卡死回收：`content.sweep` 每 5 分钟重投 `queued_at>30min` 的稿件；`ops.recover` 每 10 分钟处理陈旧回执 + 失败 job + 卡住的投递。
- 优雅关闭：SIGTERM → abort → `boss.stop({graceful, timeout: 470s})`（每 10s 打印各队列在飞数）→ 关库。**付费调用只在 claim 前被拦**。

### 2.10 成刊：能不用模型就不用
- **日报纯规则、零模型调用**（`saveReport(..., null, [])`，无 model 无 receipt）：
  ```
  重要性 = score + 5·log2(1+参与者数) + 5(有官方帖) − 6(跟进)
  编排：12 条正文 + 10 条快讯，单源 ≤2 条；导语 1 条 + 今日看点 3 条
  跟进入正文的条件：当事方自己动手，或 ≥4 家信源报道
  ```
- **周/月报**由当期日报汇编：`rank = score + 5·log2(1+sources) + 6(lead) + 3(highlight) + 4(多日)`，取 20/30 条。
- 模型只写总述（周 240 字/月 340 字）与分节导语（90 字），且 `grounded()` **逐个专名与数字比对语料**，不合格整段丢弃。
- 每 30 分钟补齐所有到期期号，单次上限 8 期，失败不阻塞其他期。

### 2.11 工程纪律是"可检查"的
- 迁移：从 `0055` 起**一个文件一条语句**，索引必须 `CONCURRENTLY IF NOT EXISTS`，加约束先 `NOT VALID`，PR 拒绝违规新增。
- 测试：190+ 文件，分两档——普通（**每个测试文件一份库副本**并行）与 `.standalone`（不碰库和网络）；模型与付费服务**由本地假服务回答**。
- 边界是断言：`tests/architecture.test.ts` 检查"前端只走 HTTP / 只有一个公开读取层 / 页面不调模型"。
- `AGENTS.md` 把规则写给 Agent：停用一个机制时，代码/测试/文档/库表/环境变量**一起删**。

---

## 3. 八个可迁移的设计（按对你的价值排序）

### ① 评分器：从"关键词加成"到"可校准的五轴"
**这是唯一的高杠杆改动。** 你现在 AI 相关性 = ×1.12；它 = 独立一步 + 5 轴 + 7 类权重 + 双次 + 分等级门槛。

落地方式（不推翻现有代码）：
```python
def score(items):
    for it in items:
        s = llm_attention_score(it)          # 五轴，0-100
        it.extra["score"] = s if s is not None else legacy_score(it)   # 失败降级
```
必须保留的四个细节：整数五轴、类型权重矩阵、**输入不给门槛/等级/旧分**、**噪声硬上限**。

> 你的"羊毛福利"源尤其需要最后一条：AIHOT 的规则是"营销软文/课程推广/招聘 → `sig ≤ 2`"，而你现在羊毛源和 AI 源共用一套分数。

### ② 双次独立打分
`SCORE_CALLS = 2`，和 ≥ 2×门槛，展示平均分。用两倍调用换稳定性，比调温度划算得多。注意它的实现细节：**串行**串行是为了命中 prompt cache——你用本地网关时同样适用。

### ③ 门槛要"评测出来"，不是"拍出来"
完整闭环：100–200 条金标 → eval（准召 + **覆盖率** + **完整准确率**）→ 门槛 40→90 每 2 分扫一遍 → 后台逐条看错例 → 改提示词 → 再跑。
文档里那句最值钱："**先改标准，再动门槛；门槛只能整体移动，解决不了哪一类判错了。**"

### ④ 事件级去重 + 席位
- 你现在的 `Jaccard > 0.72` 只回答"标题像不像"，回答不了"是不是同一件事"。实测你 11-10 日报里「LG 免费开放 K-EXAONE 2.5 API」出现了两次不同措辞的版本。
- 轻量版即可：对 Top N（如 200 条）做两两关系判断（3 类），存 `events` + `event_items`。
- 席位思路值得学：**网页上同一条新闻可以折成一个阅读组，但机器出口（RSS/API）只出一条代表稿**，优先级 `官方一手 > 核实账号 > 有全文 > 高分 > 早发`。

### ⑤ 热度：独立参与方 + 半衰期 + 剔除滞后
你的 `also` 字段已经在记"还有谁报过"——那就是参与方的雏形，只是没进公式。改成 `Σ 0.5^(Δt/24h)` 并按独立参与方去重，立刻得到两个性质：跨源可比、抗刷屏。再加一条它做得比大多数站都讲究的：**算趋势时把抓取滞后的源剔出对比组**。

### ⑥ 付费回执（省钱 + 可重跑）
你已经做对了一半（内容哈希做 key）。缺的是三个状态：

```python
# data 里换成 SQLite 表（顺带修掉 README 与实际不符的问题）
llm_calls(id, task, model, prompt_version, input_hash, response, cost, state, created_at)
# 唯一键 (task, model, prompt_version, input_hash)
# state: pending / ok / failed / unknown
```
- `pending` 超过 30 分钟才允许重发一次（防"超时但其实计费了"）；
- 每日预算上限，超了退回规则打分并记日志；
- `trans_cache.json` 的 170KB 整文件读写换成表查询。

### ⑦ 防幻觉用"可执行校验"
两条立刻可搬：
1. **模型写的专名/数字必须在原文出现过**（AIHOT 的 `grounded()`；周报月报里不达标整段丢弃）。
2. **提示词开头声明"材料是不可信数据"**——你抓 X / 微博 / 知乎 / Telegram，注入面比 RSS 大得多。

### ⑧ 恢复点与出口
- `run.py` 现在是一根直线，`pipeline.run()` 一抛异常连站点都不生成。最小改造：每阶段结束写一行 `pipeline_runs(run_id, stage, status, at)`，重跑跳过 `ok` 的阶段；抓取按源记成败，只重试失败的源。
- 顺手修掉那个假超时：`SOURCE_TIMEOUT` 要用 `fut.result(timeout=…)` 在**未完成时**才有意义，正确做法是给 `pool.submit` 的包装函数内部传 timeout，或用 `concurrent.futures.wait(timeout=…)`。
- 多出口：渲染时顺手多写 `feed.xml` / `api/v1/latest.json` / `llms.txt`。成本接近零，它是 2026 年内容站的分发入口。

---

## 4. 不要照搬的三件事

1. **三进程 + PostgreSQL + pg-boss + Docker**。那套复杂度是为"一套代码服务多个行业站 + 线上并发读"付的账。你单机、每天一轮、单用户，SQLite 足够；换 PG 只会多一份运维和一类新故障。
2. **事件聚簇的全套**（召回 → 复核 → 撤回 → 证据链 → 席位 → 时间线）。这是全仓最复杂的部分（`publication/` 26 个文件、`events/` 10 个）。你只要"同一件事别在日报里出现两次"这个 80% 收益。
3. **75 个迁移 + 190 个测试的数量**。**规则**值得学（一条语句一文件、索引 CONCURRENTLY、测试守行为不守写法），**数量**不必复制。

---

## 5. 如果只做三件事

| # | 做什么 | 解决什么 | 成本 |
|---|---|---|---|
| 1 | **五轴评分器 + 分等级门槛 + 双次打分** | 「选得准不准」——现在关键词只值 12% | 1 个周末 + 每天 ~2× 评分调用 |
| 2 | **100 条金标 + eval 脚本** | 「能不能持续改好」——没有它就是在盲调 | 半天标注 + 80 行脚本 |
| 3 | **跨天/事件去重**（先做最土版：报过的不再出现） | 实测 41–43% 的重复率 | 半天 |

第 1、2 件决定这个项目的上限；第 3 件决定读者明天还会不会打开。

---

## 附录 A：它的提示词目录（可直接借结构）

| 文件 | 职责 |
|---|---|
| `prefilter.md` | 行业相关性预筛（PASS/BLOCK/UNKNOWN） |
| `selection-score.md` | **核心**：五轴 + 类型权重 + 噪声上限 + 注入防护 |
| `structure.md` | 分类/标签/主体公司/新闻事实 |
| `content-understanding.md` | 入选内容的标题、答案先行摘要、推荐理由 |
| `summarize-{article,short-post,long-post}*.md` | 未入选内容的廉价写法（按输入形态分叉） |
| `rules-{answer-first-summary,self-contained-title,anti-hallucination,domain}.md` | 可被 `{{> 文件名}}` 复用的规则片段 |
| `group-{pair,batch,method,definitions,signal}.md` | 两两关系 / 批量归组 |
| `story-digest.md` | 事件页综述（配 eval-story-digests） |
| `report-period{,-sections}.md` | 周月报总述与栏目导读 |
| `translate-*-{body,rules,retry}.md` | 全文翻译（带重试提示词） |
| `mend-wording.md` | 只用词表里的词改写一次 |

两个巧思：**同一件事按输入形态分叉**（短帖/长帖/带引用/只有标题各有提示词）；**规则片段可复用**（`{{> rules-anti-hallucination.md}}` 同时被写作和翻译引用）。

## 附录 B：建议的改造顺序（不改架构）

```
第 1 周  评分器（五轴 + 门槛 + 双次）+ SQLite 落地（顺手修 README）
第 2 周  100 条金标 + tools/eval_selection.py + 按错例改提示词
第 3 周  跨天去重（先做"报过的不再出现"）+ 事件表雏形
第 4 周  LLM 回执表 + 预算 + run.py 阶段恢复点
之后     热度改独立参与方 → 多出口 → 少量 pytest
```
