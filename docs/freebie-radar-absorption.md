# freebie-radar 能力吸收记录

> 本项目（`Get_Information` · 信息雷达）从 `freebie-radar`（作者 ZiChuanLan，
> `github.com/ZiChuanLan/freebie-radar`）移植的判定逻辑清单。
> 用于日后追溯来源、判断口径分歧时该信哪一边。

## 已吸收（含本轮）

| 本项目模块 | 上游来源 | 吸收内容 | 提交 |
|---|---|---|---|
| `collector/evidence.py` | `enrich/evidence.ts` | claim / promotion / editorial / repository 四信号 | 早期 |
| `collector/obtain.py` | `enrich/obtain.ts` | 获取方式正交维度（抽奖>推广>试用>有条件>free） | 早期 |
| `collector/openrouter.py` | `openrouter.ts` | OpenRouter 免费模型抓取口径 | 早期 |
| `config/feeds.yaml` | `SEEDS` 源清单 | DeepFlood / Solidot / 阮一峰 / 雷锋网 / 小众软件 / Google新闻科技 6 源 | 早期 |
| `docs/feed-pitfalls.md` | `docs/data-sources.md` | 信源踩坑实测记录 | 早期 |
| `collector/codes.py` | `enrich/codes.ts` | 兑换码/邀请码提取（显式标注/分段码/大写串 + plausible 闸门） | 本轮 |
| `collector/pricing.py` | `enrich/pricing.ts` | 价格提取（USD→CNY、is_free 只看标题、NEGATIVE 上下文反例） | 本轮 |
| `collector/noise.py` | `enrich/noise.ts` | DEAL/PROMO/OPENSOURCE/NON_FREEBIE/WIDE_AI_TRIGGER/URGENT 六套信号 + 噪音标题 | 本轮 |
| `collector/blocklist.py` | `enrich/blocklist.ts` | 统一屏蔽词（关键词/正则双模式、scope 按源） | 本轮 |
| `config/blocklist.yaml` | 上游预设词表 | 16 条预设噪音词，配置驱动 | 本轮 |

## 移植时的本地化改造

- **屏蔽词：DB → 配置**。上游是 SQLite `block_rules` 表 + 界面增删；本项目改为
  `config/blocklist.yaml`，`preset: false` 可关内置词，改完下一轮生效，不引入新表。
- **`codes.py` 扩展了 `=` 分隔符**（`code=XXX` 在中文福利帖常见），上游只有 `:`/空格。
- **`noise.py` 的 how-to 例外**调用了本项目 `evidence.content_signals()`，
  而非上游的 `contentSignals()`，语义一致。

## 尚未吸收（明确记录，避免重复劳动）

- **信源差集**：NodeSeek / NodeLoc / 福利吧 / VPS 促销线（LowEndTalk 等）/ 游戏限免
  （Epic/Steam/GamerPower/CheapShark）/ 软件限免 / Reddit 白嫖社区 / GitHub 清单源。
  加之前先看 `docs/feed-pitfalls.md`，按「探针测通再入清单」的规矩办。
- **网络拓扑判据**：上游「被墙源走海外 VPS、本机只跑国内站」的分出口部署（data-sources.md 第 0 节），
  与 FlareSolverr 过盾方案，尚未写入本项目运维文档。
- **`enrich/ai*.ts` 系列**（ai-queue / ai-telemetry / ai-settings）：本项目已有
  `llm.py` + `valves.py` 覆盖回执/预算/换模型，无需移植。
- **`enrich/dedup.ts` / `alias.ts`**：本项目 `identity.py` 已有 URL 规范化 + 平台 ID + 标题相似度，
  口径不同，暂不合并（避免两套去重打架）。

## resource-site 盘点结论

`resource-site`（资源盒子）主要是创作工具导航（UI/提示词/小红书/小说等 9 类），
与信息雷达主题重合度低。仅 3 条沾边：Firecrawl（可增强 `extract.py` 的 JS 页兜底）、
Agent-Reach（跨平台热点采集）、GitHub 仓库搜索 API（已覆盖）。本轮未吸收。
反向更合理：把本项目的 `llms.txt` / `feed.xml` 作为一条资源收进资源盒子。
