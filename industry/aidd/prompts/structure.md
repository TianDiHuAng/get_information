# 结构化：分类、标签、主体、事实

只输出 JSON。

## 分类（category，只能从这 8 个里选一个）

- `platform_release` 平台发布：新的 AIDD 平台、模型、引擎正式发布或大版本更新
- `pipeline_progress` 管线进展：候选分子进入临床前/临床、里程碑达成、项目终止
- `clinical_data` 临床数据：临床试验读出、疗效与安全性数据、终点达成
- `research_paper` 论文研究：论文、预印本、方法学研究
- `tool_or_method` 工具方法：可直接复用的开源工具、流程、建模方法
- `industry_event` 融资合作：融资、并购、BD 授权、合作、人事
- `regulatory` 监管审批：获批、受理、指导原则、监管政策
- `dataset_benchmark` 数据与评测：公开数据集、benchmark、评测榜单

## 标签（tags，只能从词表里挑，最多 3 个）

靶点发现 / 分子生成 / 蛋白质设计 / 抗体设计 / 多肽 / 小分子 / ADMET /
虚拟筛选 / 分子对接 / 自由能计算 / 生成模型 / 扩散模型 / 强化学习 /
知识图谱 / 单细胞 / 多组学 / 临床试验 / 真实世界数据 / 开源 / 数据集

## 主体（subjects）

报道里作为主体的公司、机构、药物名，最多 3 个，用原文里的写法。
没有明确主体就留空数组。

## 范围（scope）

- `single`：一条具体新闻（一件事）
- `roundup`：多件事打包的综述、周报、行业报告

## 事实（fact，仅 scope=single 时填写）

- `who`：谁（公司/机构）
- `what`：做了什么（动词短语）
- `target`：针对什么（靶点/疾病/技术）
- 三者都必须能在原文找到依据；找不到就填 null

只输出 JSON：
{"category": "", "tags": [], "subjects": [], "scope": "single", "fact": {"who": null, "what": null, "target": null}}
