# 怎么把信息收“全”

> 结论先说：**“全”不是堆 RSS 数量，而是四层互补 + 每条通道真的通 + 跨源去重。**
> 单一开源项目都收不全：Horizon 强在 AI 管线，TrendRadar 强在国内热榜，RSSHub 强在长尾覆盖。

## 一、四层模型（缺一层就会漏一整类信息）

| 层 | 作用 | 典型源 | 漏了会怎样 |
|---|---|---|---|
| **榜单层** rank | 热度信号，告诉你“大家在聊什么” | HN、GitHub Trending、B站排行、头条热榜、微博/知乎热榜、V2EX | 只有长文，没有“当下最热” |
| **广谱层** broad | 稳定订阅，覆盖固定作者/媒体 | 博客 RSS、36氪、少数派、arXiv、公众号、播客 | 深度内容缺失 |
| **搜索层** search | 长尾兜底，覆盖没有 RSS 的站点 | Google News RSS、GDELT、Bing News、X 关键词搜索、搜狗微信 | 突发事件、小众话题抓不到 |
| **社媒层** social | “人”比“媒体”快 | X 列表、Telegram 频道、Reddit、即刻 | 一手消息慢半天 |

## 二、每条通道的真实可用性（本机实测 2026-11-06）

| 源 | 通道 | 实测 | 备注 |
|---|---|---|---|
| Hacker News | 直连 API | ✅ 200 | 稳定 |
| GitHub | 直连 API | ✅ 200 | 未登录 60 次/时 |
| arXiv | 直连 API | ✅ 200 | |
| B站排行 | 直连 API | ✅ 200 | 需 Referer |
| 头条热榜 | 直连 API | ✅ 200 | |
| 36氪 / 少数派 | 直连 RSS | ✅ 200 | |
| Google News | **代理** | ✅ 200 | 必须走 `socks5h://127.0.0.1:10808` |
| 微博热搜 | Cookie | ❌ 403 | 需登录态 cookie |
| 知乎热榜 | Cookie | ❌ 401 | 需登录态 cookie |
| Reddit | 代理 | ❌ 403 | 数据中心 IP 被拦，需住宅代理或换 RSS |
| Telegram | 代理 | ❌ 超时 | 需自建 RSSHub 或 MTProto |
| GDELT | 代理 | ❌ 429 | 限流严格（~1 次/5 秒） |
| rsshub.app 公共实例 | 直连/代理 | ❌ 403 | Cloudflare 拦，**必须自建** |
| X / Twitter | **fxtwitter 镜像** | ✅ 200（走代理） | `/2/profile/{user}/statuses` 免费无需 token；官方 API 免费档读不了，Apify 仅备选 |

**关键结论**：墙外源必须走本机代理；微博/知乎必须带 Cookie；RSSHub 公共实例已不可用，长尾覆盖要靠自建实例。


## 三、一手源头清单（按“追 AI 前沿”的思路）

| 源 | 内容 | 机器可读通道 | 接入状态 |
|---|---|---|---|
| [smol.ai AINews](https://news.smol.ai) | 每天一篇，社区/产品/论文汇总 | RSS 已停更（最后 2026-09-09）→ 解析首页卡片 + latent.space 详情页摘要 | ✅ 已接 |
| [The Batch](https://www.deeplearning.ai/the-batch/) | 吴恩达团队周报，带行业判断 | 无 RSS → 解析列表页，按日期倒序 | ✅ 已接 |
| [HF Daily Papers](https://huggingface.co/papers) | 社区投票的当日热门论文 | `GET /api/daily_papers`（需代理） | ✅ 已接 |
| [arXiv cs.AI](https://arxiv.org/list/cs.AI/recent) | 最原始的一手论文 | `export.arxiv.org/api/query`（直连） | ✅ 已接 |
| [alphaXiv](https://www.alphaxiv.org) | 论文评论区 | 无公开 API，页面为 RSC 渲染 | ⏸ 需浏览器渲染 |
| [LMArena](https://lmarena.ai) | 模型盲测榜 | Cloudflare 403，无公开 API | ⏸ 需浏览器/住宅 IP |
| [Artificial Analysis](https://artificialanalysis.ai) | 模型质量/速度/价格对比 | 无公开 API，页面 1.4MB 动态渲染 | ⏸ 可做定期快照 |

**实测教训**：`news.smol.ai/rss.xml` 仍返回 200 且能解析，但内容停在 2026-09-09；站点首页却每天更新。
只信 RSS 会静默漏掉两个月——所以每个源都要有“最后更新时间”健康检查。

后三个（alphaXiv / LMArena / Artificial Analysis）本质是**榜单和讨论区**，不是新闻流，更适合做“每周快照 + 变化对比”，而不是塞进日报。

## 四、已验证的最小骨架

`collector/` 里是一个能跑的采集层，8 个源并发抓取 → 归一化 → 去重 → 打分 → 静态站：

- 统一模型 `Item(source, layer, title, url, published, summary, heat, lang, extra)`
- 去重：URL 规范化（去 utm 等）+ 标题二元组 Jaccard > 0.72 合并同事件
- 打分：`0.4×时效 + 0.4×热度分位 + 0.2×层级权重`
- 输出：`data/items.json` + `site/index.html`（截图见 `site/_preview.png`）

跑一次：`python run.py`

## 五、要补到“真·最全”，还差三块

1. **X/Twitter**：Apify（`APIFY_TOKEN`，免费 $5/月）或 Cookie 抓取。接进来后社媒层才成立。
2. **微博 / 知乎**：登录一次拿 Cookie 存进 `.env`，走 `m.weibo.cn` 与 `zhihu.com/api/v4` 的移动端接口，比 PC 端宽容。
3. **自建 RSSHub**：`git clone` + `pnpm install` + `pnpm dev`（本机无 Docker，用 Node 直接跑）。它一活，公众号、B站 UP、小红书、即刻、Telegram、播客全部变成 RSS，长尾覆盖率直接翻几倍。

## 六、推荐的最终组合

```
RSSHub(自建) ─┐
X(Apify) ─────┤
微博/知乎(cookie) ─┼→ 统一采集层(本仓库 collector) → 去重/打分 → AI 摘要 → 静态站 + 推送
HN/GitHub/榜单 ─┤
Google News/GDELT ┘
```

定时：Windows 任务计划程序 / GitHub Actions / 云服务器 cron，每天跑一次 `python run.py`。

## 七、覆盖率不是终点

源到 30+ 之后，信噪比会崩。必须同时有：
- **关键词过滤**（只要你在意的主题）
- **跨源去重**（同一事件 5 家媒体只留 1 条 + 标注“5 家报道”）
- **AI 评分**（相关性、重要性），否则站会变成另一个信息垃圾场。
