# Get_Information · 信息雷达

每天自动采集 AI 前沿信息（一手博客 / 论文 / X / Telegram / 国内科技媒体 / 羊毛福利），
去重打分后生成一个本地可视化站点 + 每日邮件日报，每周一份 arXiv（AI 制药）周报。

## 功能

- **多源采集**：20+ 源（实验室博客、arXiv、HF Papers、HN、GitHub、X、Telegram、微博、知乎、36氪、IT之家…）
- **中文阅读**：非中文条目自动翻译成简体中文（带缓存）
- **分层打分**：时效 / 热度 / 来源权重 + AI 关键词加权，跨源去重
- **三块产出**：网站（国外 / 国内分区）、每日邮件日报、每周论文周报
- **本地存储**：SQLite 无依赖，全部产物在 `data/`

## 快速开始

```bash
# 1) 依赖
pip install requests beautifulsoup4 pyyaml pandas pyarrow

# 2) 准备配置（example → 真实文件，填自己的 key）
cp config/llm.example.yaml     config/llm.yaml
cp config/mail.example.yaml    config/mail.yaml
cp config/secrets.example.yaml config/secrets.yaml
cp config/cookies.example.yaml config/cookies.yaml
cp config/aa.example.yaml      config/aa.yaml

# 3) 跑一轮
python run.py

# 4) 看站点
python serve.py        # http://localhost:8123
```

定时：`watchdog.bat`（Windows）按 03:00 / 09:00 / 15:00 / 21:00 跑，9 点那轮发日报。

## 配置说明

| 文件 | 作用 |
|---|---|
| `config/feeds.yaml` | 额外 RSS 源，加源只改这里 |
| `config/x.yaml` | X 账号名单 + 关键词搜索矩阵 |
| `config/telegram.yaml` | Telegram 公开频道 |
| `config/domestic.yaml` | 微博/知乎：热搜 or 关键词搜索 |
| `config/topics.yaml` | AI 关键词 / 国内准入词 / 羊毛词 |
| `config/papers.yaml` | arXiv 周报主题与限额 |
| `config/mail.yaml` | 邮件服务与收件人 |
| `config/secrets.yaml` | **所有 token / 密码（已 gitignore）** |

## ⚠️ 安全

`config/secrets.yaml`、`config/cookies.yaml`、`config/mail.yaml`、`config/aa.yaml`、`config/llm.yaml`
以及 `data/`、`logs/`、`site/` 都在 `.gitignore` 里，**不要提交**。

提交前可跑一次自检：

```bash
python tools/scan_secrets.py
```

## 目录

```
collector/     采集/清洗/打分/翻译/渲染/推送
config/        配置（含 example 模板）
data/          运行产物（忽略）
site/          生成的网站（忽略）
tools/         辅助脚本（cookie/token 写入、密钥扫描）
docs/          交接与源覆盖文档
```
