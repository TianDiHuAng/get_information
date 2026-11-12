# 上手

从 clone 到能在本地看到站点，大约 10 分钟。

## 0. 前提

```
Python 3.11+
能访问外网（部分源需要代理）
一个 OpenAI 兼容的模型服务（本地网关或云 API 都行）
```

## 1. 装依赖

```bash
pip install -r requirements.txt
```

只有五个包：`requests` / `beautifulsoup4` / `PyYAML` / `pandas` / `pyarrow`。
没有 Scrapy、没有 feedparser、没有向量库。

跑测试自检：

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q        # 应该 432 个全过
```

## 2. 填配置

仓库里只有 `*.example.yaml`，真的配置被 `.gitignore` 排除了。复制并改名：

```bash
cd config
cp llm.example.yaml      llm.yaml
cp secrets.example.yaml  secrets.yaml
cp mail.example.yaml     mail.yaml
cp aa.example.yaml       aa.yaml
cp cookies.example.yaml  cookies.yaml
```

四个文件分别填什么：

| 文件 | 要填的 | 从哪来 |
|---|---|---|
| `llm.yaml` | `api_key`、`base_url`、`model` | 任意 OpenAI 兼容服务 |
| `secrets.yaml` | `apify_token`、`mail_password` | apify.com / 邮箱授权码 |
| `mail.yaml` | `user`、`auth_code`、`to` | SMTP 账号与授权码 |
| `cookies.yaml` | `weibo.cookie`、`zhihu.cookie` | 浏览器开发者工具里复制 |
| `aa.yaml` | `api_key` | artificialanalysis.ai |

**`llm.yaml` 的 `base_url` 决定用哪家模型**，改这一行就能换供应商，代码不用动：

```yaml
base_url: "http://127.0.0.1:8788/v1"   # 本机网关
# base_url: "https://api.deepseek.com/v1"
model: "glm-5.3-flash"
```

⚠️ **换模型必须重新校准门槛**，见第 6 节。

## 3. 跑一次采集

```bash
python run.py --no-mail --dry-push
```

两个开关先都关掉，避免第一次跑就发邮件/推消息。

一次完整跑会做：抓取 → 正文提取 → 去重 → 结构化 → 评分 → 事件聚簇 → 综述 → 生成日报。

耗时从几分钟到十几分钟，取决于信源数量和模型速度。产物：

```
data/radar.db      SQLite 主库（19 张表）
data/items.json    站点构建用的快照
data/daily/*.md    每期日报的 Markdown
```

## 4. 生成站点

```bash
python tools/build_both.py
```

一条命令建两站：

```
site/         AI 站（约 470 页）
site/aidd/    AIDD 制药站（约 120 页）
```

也可以分开建：

```bash
python tools/build_sites.py --site site --data data --db data/radar.db
RADAR_PACK=aidd python tools/build_sites.py --site site/aidd --data data-aidd \
  --db data/aidd.db --base /aidd
```

## 5. 本地预览

```bash
python serve.py
```

默认 8124 端口，启动后会打印本机和局域网地址（手机连同一 Wi-Fi 可直接看）。

- `http://localhost:8124/` — AI 站
- `http://localhost:8124/aidd/` — AIDD 站
- `http://localhost:8124/admin.html` — 后台（要口令，第一次运行会在 `data/admin_token.txt` 生成）

服务会自动带上**每日 09:00 采集**的调度线程（见 `serve.py` 的 `_daily_scheduler`）。
不想要就把那段注释掉，改用系统计划任务调 `run_daily.bat`。

## 6. 校准门槛（重要）

`config/scoring.yaml` 里那组门槛（46/54/56/62/64）是**用 99 条人工标注算出来的**，
只对当时的模型和行业成立。换模型、换行业都要重来：

```bash
python tools/make_gold.py          # 生成待标注样本 → data/gold.jsonl
# 手工在 data/gold.jsonl 里标 select / reject / either
python tools/eval_selection.py     # 看准确率/召回/F1，扫门槛
python tools/reselect.py           # 用新门槛重算，不用重新评分
```

不校准的后果：要么全放行（看着热闹，其实没筛），要么全拦下（首页空的）。

## 7. 换行业

详细步骤见 [`docs/customize.md`](docs/customize.md)，大致是：

```bash
python tools/customize.py new aidd     # 生成 industry/aidd/ 骨架
python tools/probe_feeds.py            # 探测候选 RSS 是否可用
python tools/customize.py check        # 校验配置一致性
python tools/customize.py use aidd     # 切换
```

现有的 `industry/aidd/` 是制药行业的完整示例，照着改最快。

## 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `RADAR_PACK` | 用哪个行业包 | 空（AI 主站） |
| `RADAR_DB` | 数据库路径 | `data/radar.db` |
| `RADAR_DATA` | 数据目录 | `data/` |
| `RADAR_SITE` | 站点输出目录 | `site/` |
| `RADAR_PORT` | 预览端口 | 8124 |
| `RADAR_COLLECT` | 是否真的抓取 | 开 |
| `RADAR_MODEL` | 是否真的调模型 | 开 |
| `RADAR_PUSH` | 是否真的推送 | **关** |

后三个是安全阀，`RADAR_PUSH` 默认关闭——不显式打开不会发邮件/推消息。

## 常见问题

**抓不到内容 / 全是英文源失败**
多数源在墙外，需要代理。在 `config/*.yaml` 里配 `proxy`，或设 `COLLECTOR_PROXY`。

**微博/知乎热榜空了**
Cookie 过期了。重新从浏览器复制，覆盖 `config/cookies.yaml`。

**模型调用失败**
先确认 `llm.yaml` 的 `base_url` 能通：

```bash
curl http://127.0.0.1:8788/v1/models -H "Authorization: Bearer 你的key"
```

**首页是空的**
门槛太高（见第 6 节），或 `RADAR_MODEL=0` 导致没评分。

**站点样式变了但页面没变**
先 `python tools/build_both.py`，再 `Ctrl+Shift+R` 强刷。

## 目录结构

```
collector/      pipeline、评分、聚簇、站点生成（框架，不含具体行业）
modules/        可选模块（模型榜、Token 羊毛）
industry/       行业包（aidd 是完整示例）
config/         配置 + prompt
tools/          命令行工具
tests/          432 个测试
docs/           定制手册与分析文档
data/           运行时数据（gitignore）
site/           生成的静态站（gitignore）
```

## 工具一览

| 命令 | 用途 |
|---|---|
| `python run.py` | 跑一次完整流水线 |
| `python tools/build_both.py` | 重建两站 |
| `python serve.py` | 本地预览 |
| `python tools/probe_feeds.py` | 批量探测 RSS 可用性 |
| `python tools/customize.py check` | 校验行业包配置 |
| `python tools/make_gold.py` | 生成标注样本 |
| `python tools/eval_selection.py` | 评估与门槛扫描 |
| `python tools/reselect.py` | 按新门槛重算 |
| `python tools/scan_secrets.py` | 推代码前扫密钥 |
| `python tools/make_brand.py` | 从一张图生成全部品牌资源 |
| `python tools/shoot.py` | 无头浏览器截图验排版 |
| `mcp_server.py` | MCP 接入（7 个工具） |
