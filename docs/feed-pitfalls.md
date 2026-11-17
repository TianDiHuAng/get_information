# 加源之前先看这份：踩过的坑

给情报雷达加新源时，最贵的成本不是写抓取器，是**在不可用的源上反复试**。
这份文档收集两类东西：

- **外部坑**：某个站点/接口为什么拿不到，换什么路径能绕
- **内部坑**：本项目自身的实现细节，改代码时容易忽略

来源：`freebie-radar` 的 `docs/data-sources.md`（它的实测记录）+
本项目 2026-11 期间自己的探测结果。

---

## 一、外部：探测后确认不可用的源

### 1. Cloudflare / 反爬（403）

| 目标 | 现象 | 有没有绕法 |
|---|---|---|
| `linux.do` RSS | 403（Cloudflare） | 需要 FlareSolverr（Docker 常驻）或 curl 的 TLS 指纹；`requests` 一律 403 |
| `pubs.acs.org` RSS（JCIM / J Med Chem） | 403 | ✅ **绕法：走 PubMed `[ta]` 期刊检索**（见下） |
| `steamdb.info/upcoming/free` | 403 | 无 |
| `freestufffinder.com` | 403 | 无 |
| `NGA` 全部入口（`bbs.nga.cn` / `nga.178.com` / `ngabbs.com`） | 403，`15:访客不能直接访问` | 需登录态（Playwright 持久化 profile） |
| 百度贴吧 `f?kw=免费` | 403 | 无 |
| `old.reddit.com` JSON | 403 | ✅ 用 `.rss` |
| `rsshub.app` 公共实例 | 403 Cloudflare | 自建 RSSHub 或换源 |
| `hostloc` `forum.php?mod=rss` | 200 但返回 HTML 拦截页 | 无 |

### 2. 接口改版 / 下线

| 目标 | 现象 |
|---|---|
| GOG `catalog.gog.com/v1/catalog?price=free` | `price=free` / `priceBetween=0,0` / `discount=100` 三个参数**都不生效**，返回普通折扣游戏 |
| 什么值得买「白菜党」 | `/feed` 404，频道已改版 |
| `nitter.net` | 410，实例已下线 |
| `app.nga.cn/app_api.php` | 404，旧 App 接口下线 |
| `arxiv rss.arxiv.org/rss/q-bio.BM` | 端点已停用（返回空） |
| `itch.io /games/free.json` | 404，无 JSON 接口 |
| `humblebundle` API | 403；页面需 JS |

### 3. 返回的不是 feed（HTML / SPA / 损坏 XML）

| 目标 | 现象 |
|---|---|
| `36kr.com/feed` | XML 不合法（`invalid token: line 10`） |
| `jiqizhixin.com/rss` | XML `mismatched tag` |
| `pharmaphorum.com/feed` | XML `invalid token: line 6` |
| `vcbeat.top/feed` | 空 payload |
| `x.com/<账号>` | 200 HTML，但 JS 渲染 + 登录墙；单页解析不稳定 |
| `chinanews.com.cn/rss/it.xml` | 200 但 0 条 |

### 4. 网络层

| 目标 | 现象 | 解法 |
|---|---|---|
| `bioon.com` / `yaozh.com` / `yxj.org.cn` | 404 | 无 |
| `biodiscover.com` / `med.sina.com` | SSL 握手失败 | 无 |
| `tisi.org/feed` | 连接重试耗尽 | 无 |
| **`openrouter.ai`** | socks5h 与直连都 `SSL_ERROR_SYSCALL` | ✅ **只有 `http://127.0.0.1:10808` 能通** |
| **GitHub `git push`** | `OpenSSL SSL_connect: SSL_ERROR_SYSCALL` | ✅ `git -c http.sslBackend=schannel -c http.version=HTTP/1.1 push`（已写入本地 config） |

### 5. 限流（能用，但要控速）

| 目标 | 限制 |
|---|---|
| **Reddit `.rss`** | 同 IP 并发 4 路全 429；串行 9 秒间隔仍有 6/9 失败。**同源重试 1 次（隔 20 秒）即成功** |
| **NCBI E-utilities（PubMed）** | 无 key：3 次/秒。本项目 `pubmed.py` 两次调用间隔 0.4s |
| GitHub API | 无 token 60 次/小时；有 token 5000 |
| OpenRouter `/models` | 未观察到限流，但 TLS 不稳，需三路重试 |

---

## 二、绕法：几个已验证的替代路径

### 1. ACS 期刊拿不到 → 走 PubMed 期刊检索

`pubs.acs.org` 的 RSS 403，但这两本刊全在 PubMed 里：

```
"J Chem Inf Model"[ta] AND (machine learning OR deep learning OR "artificial intelligence")
"J Med Chem"[ta] AND ("artificial intelligence" OR "machine learning" OR "deep learning")
```

`[ta]` 是期刊名字段限定。命中量：JCIM 1993 条 / J Med Chem 173 条，单次取 12 条带摘要。

**这个套路可以复制到任何「RSS 反爬但被 PubMed 收录」的期刊** —— 查一下它的 `[ta]` 名即可。

### 2. 没有 RSS 的中文站 → Google 新闻专题检索

```
https://news.google.com/rss/search?q=<URL编码的检索式>&hl=zh-CN&gl=CN&ceid=CN:zh-Hans
```

实测 5/5 全通，每条约 15 条结果。比猜 RSS 地址可靠得多
（我猜的 12 个中文 RSS，只有量子位一个能用）。

### 3. X / Twitter → fxtwitter 或 XFeed

- 单个账号：`api.fxtwitter.com/<handle>`（免费、无需 token）
- 整个创作者生态：`xfeed.ai/data.json`（994 条、678 位作者、带互动数据）

---

## 三、内部：本项目自己的实现坑

### 1. `REGISTRY` 是「装饰后」的源，抓取参数不在里面

```python
# ❌ 这样拿不到 url
sid = s["id"]; url = s["url"]      # KeyError

# ✅ 回原始 feeds.yaml 查
from .sources import _feed_field
url = _feed_field(sid)
```

`REGISTRY` 只保留 `id/name/layer/access/status/enabled/tier/participation_mode`。

### 2. `build_fetchers()` 必须按 id 去重

同一个 id 注册两次会**抓两遍**，而且第二次可能走到兜底的 `rss_source`
（把 URL 编码的检索式当 RSS 地址，报 `MissingSchema`，异常被吞掉、静默失败）。

### 3. 行业包的文件不会自动覆盖全局

以下四类都要显式判断 `RADAR_PACK`：

| 文件 | 谁负责读 | 现状 |
|---|---|---|
| `feeds.yaml` | `sources._load_feeds()` | ✅ 已支持 |
| `prompts/*.md` | `rating.prompt()` | ✅ P85 修 |
| `scoring.yaml` | `rating._scoring_path()` | ✅ P86 修 |
| `topics.yaml` | `pipeline._topics()` | ✅ P83 修 |
| `site_modules.yaml` | `modules._manifest_path()` | ✅ P102 修 |

**加新配置时如果忘了这一层，AIDD 会静默用 AI 的口径跑。**

### 4. `run.py` 只给「当轮新抓到的」条目打分

改提示词/权重/门槛后，**已入库的条目不会重算**。要用：

```bash
RADAR_PACK=aidd python tools/rescore.py --day 2026-11-13
```

### 5. 测试不能写死日期

`scope.max_age_hours` 会把「写死的老日期」判为过期，第二天整批用例失败。
本仓库已踩三次（`test_site` / `test_selectbench` / `test_mcp`），统一用：

```python
def _iso(days_ago=0, hour=8): ...
def _day(days_ago=0): ...
```

### 6. Chrome 无头窗口最小约 489px

用 `--window-size=390` 截图，实际视口是 489，截图再把右边裁掉 —— **看起来像移动端溢出，其实是测试假象**。
真机仿真要用 CDP：

```bash
python tools/shoot_mobile.py --probe    # 报每页 scrollWidth - clientWidth
```

### 7. 模型返回的结构可能和代码假设不同

模型给的是 `{"axes": {...}, "itype": "监管与政策"}`（嵌套 + 中文），
而代码按顶层读五轴、按英文枚举匹配 —— `int(None)` 抛异常被 `except` 吞掉，
日志显示「调用成功」、统计显示「评分失败」，两边对不上，很难查。

**规则**：任何按条目吞异常的地方，至少留一个 `RADAR_DEBUG=1` 开关打印真实异常。

---

## 四、加源的标准流程

```bash
# 1. 先探针，别直接写代码
python tools/probe_feeds.py --file new_feeds.txt   # 每行一个 URL

# 2. 只把返回 ≥3 条的写进 config/feeds.yaml（或 industry/<pack>/feeds.yaml）

# 3. 校验配置
python tools/customize.py check

# 4. 单源试抓
python -c "from collector import sources; print([ (s,f()) for s,f in sources.build_fetchers() if s=='新id' ][0][1][:2])"

# 5. 跑一轮看入库与评分
python run.py --no-mail --dry-push
```

**探针的判据**：`OK` 且条数 ≥3 才算可用；`×` 的直接放弃，不要试图「换个 UA 再试」——
403/404 大多是结构性问题，不是 UA 问题。
