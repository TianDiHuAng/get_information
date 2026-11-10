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

# 4) 看站点
python serve.py        # http://localhost:8123
```

定时：`watchdog.bat`（Windows）每天 09:00 跑一次，并发送日报。

测试：`pip install -r requirements-dev.txt && python -m pytest tests -q`
（测试不联网、不花钱：LLM 全部用假的，数据库一律在临时目录）

## 一条条目的流程

```
采集(28 源) → 身份去重 → 老分(时效/热度/层权重) → 补正文与日期 → 重算分 → 落库(指纹/修订)
   → 预筛(LLM) → 五轴 × 2 次(LLM) → 分等级门槛 → 排序分
   → 结构化(分类/标签/主体) → 事件聚簇(粗排 → 关系判定 → 复核) → 热度 → 翻译
   → 规则编排成刊(头条/看点/正文/快讯) → 导读(LLM + grounding 校验) → 告警
```

事件聚簇的成本控制：先用 IDF 加权的 token 重合粗排，只把够像的对送进模型；
判定结果落 `event_pairs`，同一对永不重复付费。实测 215 条 → 24 次判定 → 9 个多篇事件。

两个分怎么用：

| 分 | 是什么 | 用在哪 |
|---|---|---|
| `attention.score` | 五轴加权（0–100），判断「值不值得看」 | 精选门槛、日报取舍 |
| `extra.score` | `0.8 × attention + 0.2 × 老分` | 站点排序（时效只剩轻微修正） |

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
  alerts.py    告警：源健康、缺期、预算、失败率
config/        配置（含 example 模板、评分口径、提示词）
data/          运行产物（忽略）
site/          生成的网站（忽略）
tests/         单元测试（不联网）
tools/         辅助脚本（cookie/token 写入、密钥扫描）
docs/          交接、源覆盖、AIHOT 分析与吸收路线
```
