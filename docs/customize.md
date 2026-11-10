# 把它改成你的行业

这个站默认是一个「AI 行业」的热点站：信源是一批 AI 资讯源，精选口味是在 AI 领域调的。
要把它变成「法律热点」「HR 热点」「黄金热点」，改的东西都在三个地方：

| 位置 | 管什么 |
|---|---|
| `config/industry.yaml` | 站名、slogan、出刊时间、分级门槛、当前用哪个行业包 |
| `industry/<包名>/` | 一个行业的整套判断标准（分类、词表、提示词、改用词） |
| `config/sources.yaml` | 信源的分级与参与方式（哪些进精选、哪些只作热度证据） |

代码基本不用动。

开始之前先看一眼现状：

```bash
python tools/customize.py check
```

---

## 0. 快速开始

```bash
python tools/customize.py new legal --name "法律热点"
python tools/customize.py use legal
python tools/customize.py check
```

`new` 建出这一套骨架（提示词从 AI 版拷一份，改比从零写快）：

```
industry/legal/
  taxonomy.yaml            分类、标签、实体（改成法律行业的）
  wording.yaml             读者不用的词（律所营销词、看不懂的行话）
  prompts/
    attention-score.md     ★ 最该花时间的一份：什么该选、什么该压住
    prefilter.md           预筛：这条是不是法律行业的事
    structure.md           分类、标签、主体、事实抽取
    group-pair.md          两篇报道是不是同一件事
    group-review.md        低置信度的复核
```

包的工作方式是**覆盖**：`industry/legal/` 里有同名文件就用它，没有就用 `config/` 的。
所以你可以先只改 `attention-score.md`，其它沿用 —— 后面再逐个替换。

---

## 1. 站名和文案：`config/industry.yaml`

```yaml
name: Z-Bit
tagline: 今日 AI 热点与大模型动态精选
description: 每天一份 AI 情报日报
locale: zh-CN
pack: ""                    # 留空 = 用 config/ 下的文件

edition:                    # 北京时间，HH:MM。排程、缺期告警、页面文案都读它
  daily: "09:00"
  weekly: "周一"
  monthly: "1 日"
```

几条要注意的：

- **`name` 会进所有页面标题、RSS 的 `<title>`、日报页眉、`llms.txt`**。改完记得重跑一次
  `python run.py`，静态站才会换。
- **出刊时间写整点或半点**。`edition.daily` 不是文案，缺期告警按它算。
- **`pack` 上线后不要频繁改**：换了包，历史产物的分类 key 可能对不上，
  归档页会出现空的分类。真要换，先跑 `python tools/customize.py check`。

---

## 2. 分类、标签、主题：`taxonomy.yaml`、`topics.yaml`

`taxonomy.yaml` 三块：

```yaml
categories:                 # 分类：页面上的栏目、RSS 的分类、主题页的归属
  model_release: {label: 模型发布, desc: 新模型或大版本更新}
  ...

tags:                       # 标签词表：模型只能从这里挑
  - 开源
  - 智能体

entities:                   # 公司/机构：热度去重与"主体"字段用
  - {id: anthropic, label: Anthropic, aliases: [安思罗匹克]}

plain_terms:                # 总述免核对词：出现在摘要里不算专有名词
  - AI
```

**三条硬规则**：

1. **分类 `key` 会进网址**（`/feed/category/<key>.xml`、`/topics/<key>.html`），
   上线后不要改。要改显示名，改 `label`。
2. **改完 `categories`、`tags`、`entities`，必须同步改 `prompts/structure.md`**。
   提示词里有一份"分类只能是这几个"的枚举；两边不一致，模型会输出页面不认识的类别，
   对应的分类页会永远是空的。`tools/customize.py check` 会逐个指出来。
3. **`entities` 是防张冠李戴用的**：模型写的公司名必须在原文里出现过。
   你的行业不需要这项检查时清空成 `[]`。

`topics.yaml` 是主题页目录：

```yaml
topics:
  - slug: legal-tech
    title: 法律科技
    tags: [法律科技, 合同审查]      # 打了这些标签的报道收进来
  - slug: supreme-court
    title: 最高法院
    entity: supreme-court           # 以这家机构为主体的报道
    aliases: [最高法, 最高院]        # 搜索框里搜这些词也能找到
```

`slug` 上线后不要改（它就是网址）。

---

## 3. 信源：`config/sources.yaml` + `collector/sources.py`

抓取器写在 `collector/sources.py` 的 `REGISTRY` 里（每个源的抓取逻辑是代码），
**分级与参与方式可以在 `config/sources.yaml` 里覆盖，不用改代码**：

```yaml
sources:
  - id: smolai
    tier: T1                  # T1 官方一手 / T1_5 官方账号 / T2 媒体与个人
    participation_mode: editorial
    site_fulltext: false
    owner_entity_id: anthropic
```

四个字段的含义（和 AIHOT 一致）：

| 字段 | 含义 |
|---|---|
| `tier` | 分级。不同分级用不同门槛。`T1` 就是"一手"，不用另外标 |
| `participation_mode` | `editorial` 进精选与全部动态；`hot_signal` 只作热度证据；`isolated` 不进任何公开页面 |
| `site_fulltext` | 站内能不能展示正文。**默认关**，只给摘要与原文链接。来源明确允许时才开 |
| `syndicate_fulltext` | 全文 RSS 能不能带正文。只在 `site_fulltext` 也开时生效 |
| `owner_entity_id` | 这个源属于哪家公司。同一家的多个源在热度里只算一个参与方 |

`tier` 不写会按 `layer` 推导：`primary→T1`、`rank→T1_5`、`broad/search/social→T2`。

**新增一个源**需要两步：在 `collector/sources.py` 写抓取函数并加进 `REGISTRY`，
再（可选）在 `config/sources.yaml` 里写分级。只有后者不用改代码。

后台「信源」页可以停用/启用、试抓，不用改文件。

---

## 4. 精选标准：`prompts/` —— 最值得花时间的一步

| 文件 | 作用 |
|---|---|
| `prefilter.md` | 预筛：这条资料是不是这个行业的事。宽召回，只拦明显无关的 |
| `attention-score.md` | **评分标准**：五维打分、各内容类型的权重、必须正常评价的价值、必须压住的噪声 |
| `structure.md` | 分类、标签、主体；是具体新闻还是综合稿；事实抽取（谁、做了什么、对什么） |
| `group-pair.md` | 两篇报道是同一次发生、同一事件的后续，还是两件事 |
| `group-review.md` | 低置信度配对的复核 |

**建议的做法**：先保留结构（五维加权、噪声压制、安全边界），
只把"什么算重要""什么算噪声"的例子换成你的行业。比如法律行业：

- **必须正常评价**：新法规正式公布、重要判决、监管处罚、大所合并
- **必须压住**：律所营销软文、课程广告、"十大常见误区"这类SEO文

提示词里用 `{{site_name}}` 指代站名。改提示词不用改代码；
提示词一改，`prompt_version` 跟着变，旧的 LLM 回执自动失效，不会拿旧结果糊弄你。

---

## 5. 门槛与校准：`industry.yaml` 的 `tiers`

```yaml
tiers:                      # 两次打分之和 ≥ 2×门槛才够分
  T1: 58
  T1_5: 66
  T2: 68
browse_floor: 40            # "全部动态"的最低分
```

**这三档是 AI 行业校准出来的，换行业必须重新定。** `tools/customize.py check`
会在你没写 `tiers` 时提醒你。

校准三步（和 AIHOT 的 `docs/selection.md` 一致）：

```bash
# 1. 分层抽样，保证每个分类都有样本（不是纯按分数挑难例）
python tools/make_gold.py --per-stratum 10

# 2. 在后台「标注」里逐条打「选 / 不选 / 两可」
#    http://localhost:8123/admin.html?tab=better
#    标进开发集；最后留 20 条标进留出集

# 3. 评测：调提示词只看开发集，最后用留出集验收
python tools/eval_selection.py --enrich --split development
python tools/eval_selection.py --enrich --split holdout
```

**留出集只在最后用一次。** 反复盯着同一批样本改提示词，会把它调成"只会做这几道题"。

评测报告在 `data/eval/*.json`，后台「评测」标签能逐条看判错、看分歧、按分层看准确率。

---

## 6. 品牌

- **站名与标志**：`config/industry.yaml` 的 `name`；页面左上角的字标读它。
- **分享图**：`collector/share.py` 用 Pillow 画 1200×630 卡片，标题取当天头条。
  换行业后不用改代码，标题会自动跟着内容走。
- **分享图字体**：`share.py` 会按顺序找中文字体，找不到就不画图（而不是画方块）。
  要指定字体，把 `.ttf` 放进 `assets/fonts/`，按文件名排序取第一个。

---

## 7. 页面文案

- **关于 / 条款 / 隐私 / 更新日志 / Agent 接入**：`collector/site.py` 里的
  `_ABOUT`、`_TERMS`、`_PRIVACY` 与 `build_static()`。**条款与隐私现在是模板**，
  上线前按你的实际情况改写，必要时请专业人士看一下。
- **页脚与导航**：`collector/theme.py` 的 `SECTIONS`（侧栏分组）与 `footer_html()`。
- **日报/周报页眉**：`collector/digest.py` 与 `collector/report.py`。

---

## 8. 模型

`config/llm.yaml`：任何 OpenAI 兼容接口都行。

```yaml
base_url: http://127.0.0.1:8788/v1
model: glm-5.3-flash
backup_model: ""            # 备用模型，主模型连续失败时切
budget_per_day: 0           # 每天调用上限（0 = 不限）
budget_per_hour: 0
```

**用推理模型时注意**：给它留出推理额度，否则推理会把输出额度用光，答案为空、
每次调用都失败。`max_tokens` 要按"推理 + 答案"一起算。

---

## 改完以后检查

```bash
python tools/customize.py check          # 跨文件一致性（分类/标签/主题/信源/门槛/词表）
python -m pytest tests -q                # 全套测试
python run.py --no-mail --dry-push       # 跑一轮，不发信不推送
python serve.py                          # 打开看首页、全部、日报、主题、关于
```

`check` 会指出这些具体问题：

| 代码 | 意思 |
|---|---|
| `prompt.category` | 分类改了但提示词没同步 —— 那个分类页会永远是空的 |
| `prompt.missing` | 缺一份提示词，对应阶段会静默降级 |
| `taxonomy.dup` | 分类 key 重复 —— 订阅地址会打架 |
| `topic.tag` / `topic.entity` | 主题引用了不存在的标签/实体 —— 那个主题页永远是空的 |
| `source.owner` | 信源指向的实体不存在 —— 热度会把同一家公司算成两家 |
| `threshold.drift` | 分级门槛和 `scoring.yaml` 对不上 |
| `threshold.uncalibrated` | 换了行业却沿用 AI 行业的门槛 —— 最容易忘、后果最大 |
| `wording.regex` | 改用词的正则写坏了 |

**跑测试时注意**：`tests/` 里有些用例用的是 AI 行业的分类与实体
（`model_release`、`anthropic`）。改了 `taxonomy.yaml` 之后它们会失败，
把例子换成你行业的对应项即可，测的规则本身不用改。

然后打开网站看一眼：首页、全部动态、日报、主题页、关于页，
再去后台「信源」页看是不是都抓成功了。
