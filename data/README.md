# data/ 数据保护约定

这个目录里**只有两个文件进 git**（通过 `.gitignore` 白名单放行）：

| 文件 | 内容 | 为什么进 git |
|---|---|---|
| `items.json` | 每轮采集的条目（标题/URL/摘要/评分/五轴/结构） | 展示站的唯一数据源，丢了站就空了 |
| `radar.db` | SQLite：条目、评分、事件、运行记录 | 跨天去重/已报抑制的历史状态 |

其余文件（`admin_token.txt`、`aidd.db`、`last_daily.txt`、`tg_seen.json`、各类 `*.log`）
**永不进 git**——含口令或纯运行态，泄露/冲突风险大。

## 为什么这么设计

`site/`（网站产物）仍在 `.gitignore` 里不进 git，因为它能从 `items.json` 重建。
但 `data/` 以前整体被忽略，导致一次误切分支就把数据全冲掉、无法恢复。
现在把「不可重建的数据」纳入版本控制，「可重建的产物」继续忽略。

## 数据丢了怎么恢复

两条路，按优先级：

1. **从 git 恢复**（首选）：这两个文件在 master 上有提交历史，`git checkout master -- data/items.json data/radar.db` 即可。
2. **从站点 API 快照恢复**：站点发布在 gh-pages，其 `api/v1/latest.json` 是从 items.json 构建的公开读取层，保留 200 条核心数据。运行：

   ```bash
   python tools/restore_data.py                 # 从 site/api/v1/latest.json 恢复到 data/
   python tools/restore_data.py --dry-run       # 先预览不写
   ```

   恢复后运行 `python tools/build_sites.py` 重建站点。
   注意：LLM 回执/预算等运行态无法从公开数据逆推，需要重新跑一轮 `run.py`。

## 日常约定

- 改完数据（`run.py` 跑完）后，把 `items.json` 和 `radar.db` 一起提交，作为当日快照。
- 不要 `git add data/` 整目录——白名单虽已挡住敏感文件，但显式只加这两个更稳。
- 切分支用 `git checkout <branch>`，不要用 `git checkout -f`（强制切换会覆盖未跟踪文件，是上次数据丢失的原因）。
