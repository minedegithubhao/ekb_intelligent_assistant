# 评估模块整理说明

本文档用于梳理当前 RAG 项目中评估模块的实际落地情况，重点说明“评估什么、数据如何流转、结果如何落库、前端如何展示、后续如何扩展”。文档内容基于当前后端项目 `ekb_intelligent_assistant` 和前端项目 `ekb_intelligent_assistant_web` 的代码实现整理，可作为后续制作 PPT 中“评估模块设计与实现”内容页的基础材料。

从当前实现看，评估模块不是一个独立的离线脚本，而是已经接入管理端页面、数据库和后端接口的功能闭环。它的核心作用是把 RAG 系统中两个关键质量问题显性化：一是知识入库后的 chunk 质量是否可靠，二是用户问题进入检索链路后，FAQ 和知识库内容是否能够被正确召回。

## 1. 当前模块定位

当前项目中的评估模块已经落地为两类评估能力，并预留了端到端评估类型：

| 评估类型 | 数据库取值 | 当前含义 | 是否已接入页面 |
| --- | --- | --- | --- |
| 入库质量评估 | `ingestion_quality` | 评估知识库 chunk 质量，包括低质量 chunk、过短、过长、重复等 | 是 |
| 检索评估 | `retrieval_eval` | 从标准问题出发，评估 FAQ 和知识库召回效果，包括 FAQ Hit Rate@K、KB Recall@K、KB MRR | 是 |
| 端到端评估 | `end_to_end` | 预留类型，当前尚未实现完整“问题 -> 检索 -> 生成 -> 引用 -> 答案质量评分”链路 | 否 |

当前前后端实际使用的是：

```text
入库质量评估：ingestion_quality
检索评估：retrieval_eval
```

需要注意：当前“检索评估”不是完整端到端评估，它不评估 LLM 答案质量、引用准确性和忠实性，只评估检索召回结果。

从 PPT 表达上，可以把当前模块概括为“入库质量评估 + 检索效果评估 + 端到端评估预留”。其中入库质量评估面向知识库建设过程，帮助发现 chunk 过短、过长、重复、低质量等问题；检索评估面向真实问答链路的前半段，使用标准问题集验证 FAQ 和知识库召回是否命中预期内容。端到端评估目前只是保留类型，后续可在现有 4 表结构上继续扩展答案质量、引用准确性和忠实性评分。

## 2. 后端模块结构

后端评估相关代码主要分布如下：

```text
app/
  api/routers/admin_evaluation.py        # 管理端评估接口
  services/evaluation.py                 # 评估集、评估任务、落库和执行编排
  schemas/evaluation.py                  # 评估接口请求/响应 schema
  db/models/evaluation.py                # 评估模块 4 张 ORM 表
  evaluation/
    ingestion_quality/
      runner.py                          # chunk 质量评估核心逻辑
      schemas.py                         # chunk 质量评估结果结构
      milvus_source.py                   # 从 Milvus 读取真实知识库 chunk
    retrieval/
      schemas.py                         # 检索评估内部数据结构
      metrics.py                         # RAGAS/本地回退指标计算
      real_adapter.py                    # 真实 retrieve_answer 结果转评估 trace
      trace_adapter.py                   # debug_retrieval 字典结果转评估 trace
      runner.py                          # 脚本化检索评估 runner
      cli.py                             # 命令行入口
    common/
      dataset_loader.py                  # 文件评估集读取工具
      file_utils.py                      # 文件输出工具

resources/evaluation/datasets/
  chunk_quality_enterprise.json          # 入库质量评估临时企业 chunk 数据
  chunk_quality_personal.json            # 入库质量评估临时个人 chunk 数据
  mock_retrieval_eval.json               # 检索评估示例样本

scripts/sql/
  005_init_evaluation.sql                # 评估模块建表 SQL
```

后端整体采用“接口层 + 服务编排层 + 评估算法层 + 数据模型层”的组织方式。`admin_evaluation.py` 负责暴露管理端接口，`services/evaluation.py` 负责评估集管理、任务创建、执行编排和落库，`app/evaluation/` 下的子模块负责具体指标计算和数据适配，数据库模型则统一承接评估集、样本、任务和单题结果。

这种结构的好处是边界比较清晰：入库质量评估和检索评估可以拥有各自的 runner、schema 和指标逻辑，但它们最终都通过同一套 run/result 表进入管理端，便于后续做历史记录、版本对比和统一展示。

## 3. 前端模块结构

前端评估相关代码主要分布如下：

```text
src/
  api/adminEvaluation.js                 # 评估模块接口封装和字段映射
  views/admin/index.vue                  # 管理端页面，包含评估管理区域
  layouts/AdminLayout.vue                # 后台菜单，包含“评估管理”
```

前端“评估管理”当前分为四个 tab：

| Tab | 作用 |
| --- | --- |
| 评估集管理 | 创建评估集、查看样本、导入样本、删除评估集 |
| 入库质量评估 | 选择知识库版本和阈值，执行 chunk 质量评估，展示问题 chunk |
| 检索评估 | 选择评估集、知识库版本、FAQ TopK、KB TopK，执行检索评估，查看单题召回详情 |
| 评估记录 | 查询历史 run，按类型、状态、关键词过滤，并跳转查看详情或重新执行 |

前端页面已经具备一个轻量评估工作台的形态。用户可以先维护标准评估集，再分别触发入库质量评估和检索评估，最后通过评估记录查看历史任务和执行结果。对于 PPT 来说，这一页可以表达为“评估模块已经形成管理端闭环”，即评估集准备、任务执行、指标展示、历史追踪都已经有对应入口。

## 4. 数据库表结构与职责

当前评估模块采用最小 4 表结构。

数据库设计遵循“先保证能跑通闭环，再逐步细化”的思路，没有为每一种指标或每一种失败明细单独拆表，而是用 JSON 字段承接配置、汇总指标、检索 trace 和评估明细。这样可以降低初期开发复杂度，同时保留后续扩展指标的空间。

### 4.1 `evaluation_datasets`

评估集表，主要服务检索评估。入库质量评估当前可以不依赖评估集。

| 字段 | 当前作用 |
| --- | --- |
| `id` | 数据库主键 |
| `dataset_id` | 评估集业务 ID，前端和接口使用 |
| `name` | 评估集名称 |
| `evaluation_type` | 评估集适用类型：`ingestion_quality`、`retrieval_eval`、`end_to_end`、`mixed` |
| `description` | 评估集说明 |
| `created_at` | 创建时间 |

### 4.2 `evaluation_cases`

评估样本表，当前主要服务检索评估。一条记录对应一个标准问题。

| 字段 | 当前作用 |
| --- | --- |
| `id` | 数据库主键 |
| `case_id` | 样本业务 ID |
| `dataset_id` | 所属评估集业务 ID |
| `question` | 标准评估问题 |
| `expected_json` | gold 信息，当前主要包含 `expected_faq_ids` 和 `expected_rule_ids` |
| `category` | 样本类型，如 `policy_fact`、`table_lookup` |
| `created_at` | 创建时间 |

当前检索评估样本的推荐结构：

```json
{
  "case_id": "eval_sample_001",
  "question": "个人/个体店出售假冒商品怎么处理？",
  "expected_json": {
    "expected_faq_ids": ["faq_001"],
    "expected_rule_ids": ["923540006109319168"]
  },
  "category": "policy_fact"
}
```

### 4.3 `evaluation_runs`

评估任务表。入库质量评估和检索评估都会在这里生成一条 run。

这张表是评估模块的主线表，代表一次完整评估任务。无论是入库质量评估还是检索评估，都会先生成 run，再把本次评估配置、执行状态、汇总指标和完成时间写入该表。后续做“本次结果 vs 上次结果”“某个知识库版本的历史趋势”“上线前回归是否通过”，都可以围绕这张表展开。

| 字段 | 当前作用 |
| --- | --- |
| `id` | 数据库主键 |
| `run_id` | 评估任务业务 ID |
| `dataset_id` | 检索评估使用的评估集 ID；入库质量评估当前为空 |
| `evaluation_type` | 当前实际使用 `ingestion_quality` 或 `retrieval_eval` |
| `knowledge_base_version` | 被评估的知识库版本 |
| `config_json` | 本次评估配置，如 `faq_top_k`、`kb_top_k`、阈值、`mock_mode` |
| `status` | 任务状态：`pending`、`running`、`success`、`failed` |
| `summary_json` | 汇总指标 |
| `detail_json` | 评估明细；入库质量评估保存完整 chunk 质量结果，检索评估保存 case 数和 mock 标记 |
| `created_at` | 创建时间 |
| `finished_at` | 完成时间 |

入库质量评估 `summary_json` 示例：

```json
{
  "chunk_count": 12000,
  "low_quality_issue_count": 340,
  "too_short_chunk_rate": 0.04,
  "too_long_chunk_rate": 0.03,
  "duplicate_chunk_count": 20,
  "duplicate_group_count": 12
}
```

检索评估 `summary_json` 示例：

```json
{
  "case_count": 50,
  "error_count": 1,
  "faq_hit_rate_at_5": 0.8125,
  "kb_recall_at_10": 0.8667,
  "kb_mrr_at_10": 0.7422
}
```

### 4.4 `evaluation_case_results`

单题评估结果表。当前主要服务检索评估。

这张表用于保存标准问题逐条执行后的结果。它不是只保存一个分数，而是同时保存召回内容、指标结果、实际回答和耗时信息，因此后续排查问题时可以回到单条 case 查看“预期是什么、实际召回了什么、指标为什么失败”。这也是评估模块从“只打总分”走向“能定位问题”的关键。

| 字段 | 当前作用 |
| --- | --- |
| `id` | 数据库主键 |
| `run_id` | 所属评估任务 ID |
| `case_id` | 所属评估样本 ID |
| `retrieved_items_json` | 单题检索 trace，包括 question、rewritten_query、faq_hits、kb_hits、debug payload |
| `metric_results_json` | 单题指标，包括 `faq_hit_at_k`、`kb_recall_at_k`、`kb_rr`、`error` |
| `actual_answer` | 真实检索链路返回的 answer；当前检索评估不用于评分 |
| `latency_json` | 当前 case 执行耗时 |
| `created_at` | 创建时间 |

`retrieved_items_json` 当前典型结构：

```json
{
  "question": "个人/个体店出售假冒商品怎么处理？",
  "rewritten_query": "个人个体店 出售假冒商品 处罚",
  "faq_hits": [
    {
      "faq_id": "faq_001",
      "rank": 1,
      "score": 0.93,
      "question": "个人/个体店出售假冒商品怎么处理？"
    }
  ],
  "kb_hits": [
    {
      "rule_id": "923540006109319168",
      "chunk_id": "923540006109319168_chunk_12",
      "rank": 1,
      "score": 0.88,
      "title": "京东开放平台个人/个体合规管理规则",
      "chunk_text_preview": "出售假冒商品的，平台可采取全店商品下架..."
    }
  ],
  "mock_mode": false
}
```

## 5. 入库质量评估

入库质量评估关注的是“知识进入向量库之后，是否具备可检索、可引用、可用于生成答案的基础质量”。它不从用户问题出发，而是直接检查知识库中的 chunk 数据，发现空 chunk、过短 chunk、过长 chunk、重复 chunk、字符分布异常等问题。

在 RAG 系统中，入库质量会直接影响后续检索和生成效果。如果 chunk 切分过碎，可能导致召回内容语义不完整；如果 chunk 过长，可能引入大量无关内容并浪费上下文窗口；如果存在大量重复 chunk，则会影响召回排序和结果多样性。因此该评估更适合作为知识库版本发布前的基础质量检查。

### 5.1 输入来源

入库质量评估当前支持两种输入：

| 输入来源 | 触发方式 | 说明 |
| --- | --- | --- |
| 临时 JSON 数据集 | 不传 `knowledge_base_version` 时使用 `dataset`，如 `enterprise`、`personal` | 文件位于 `resources/evaluation/datasets/` |
| Milvus 真实 chunk | 传入 `knowledge_base_version` 时使用 | 通过 `app/evaluation/ingestion_quality/milvus_source.py` 从知识库版本对应 doc collection 读取 |

临时 JSON 数据集字段要求：

| 字段 | 说明 |
| --- | --- |
| `dataset_id` | 数据集业务 ID |
| `user_type` | 用户类型，如 `enterprise`、`personal` |
| `document_metrics_mode` | 文档完整率模式，当前支持 `simulated` / `milvus` |
| `expected_document_count` | 期望文档数 |
| `actual_document_count` | 实际文档数 |
| `parent_chunk_size` | 父 chunk 配置大小 |
| `chunks` | chunk 列表 |

`chunks[]` 关键字段：

| 字段 | 说明 |
| --- | --- |
| `chunk_id` | chunk 唯一 ID |
| `document_id` | 所属文档 ID |
| `title` / `title_path` | 文档或 chunk 标题 |
| `chunk_type` | `text` 或 `table` |
| `is_table` | 是否表格 chunk |
| `text` | chunk 正文 |

从流程上看，入库质量评估的输入可以是临时 JSON 文件，也可以是真实 Milvus 中的知识库版本。临时 JSON 适合早期调试和演示，真实 Milvus 数据则更接近上线前评估场景。当前代码已经支持通过 `knowledge_base_version` 切换到真实知识库 chunk 数据源。

### 5.2 指标与规则

入库质量评估当前计算：

| 指标 | 说明 |
| --- | --- |
| `document_ingest_completeness_rate` | 文档入库完整率 |
| `chunk_count` | chunk 总数 |
| `duplicate_chunk_count` | 重复正文 chunk 数，不包含每组第一条 |
| `min_chunk_length` | 最短 chunk 长度 |
| `max_chunk_length` | 最长 chunk 长度 |
| `avg_chunk_length` | 平均 chunk 长度 |
| `low_quality_issue_count` | 低质量问题总数 |
| `empty_chunk_rate` | 空 chunk 占比 |
| `too_short_chunk_rate` | 过短 chunk 占比 |
| `too_long_chunk_rate` | 过长 chunk 占比 |
| `low_unique_ratio_chunk_rate` | 唯一字符比例过低 chunk 占比 |
| `duplicate_group_count` | 重复正文分组数 |

低质量问题触发规则：

| `issue_type` | 触发规则 |
| --- | --- |
| `empty` | `text.strip()` 为空 |
| `too_short` | 文本长度小于最短阈值，且不是表格 chunk |
| `too_long` | 文本长度大于最长阈值 |
| `low_unique_ratio` | 非表格 chunk、长度足够长且唯一字符比例低于阈值 |
| `duplicate_content` | 多个非空 chunk 正文 hash 相同，重复组第一条不标记，后续副本标记 |

这些指标可以分成两类理解：一类是整体质量概览，例如 chunk 总数、平均长度、过短率、过长率、重复组数；另一类是可追溯问题明细，例如每一个低质量 chunk 的 `chunk_id`、所属文档、问题类型和触发原因。前者适合做版本间对比，后者适合指导数据清洗、切分策略和入库流程优化。

### 5.3 落库方式

入库质量评估落库到 `evaluation_runs`：

| 字段 | 内容 |
| --- | --- |
| `evaluation_type` | `ingestion_quality` |
| `dataset_id` | 当前为 `NULL` |
| `knowledge_base_version` | 用户选择的知识库版本，可为空 |
| `config_json` | 阈值和数据集参数 |
| `summary_json` | 聚合指标 |
| `detail_json` | 完整 `ChunkQualityEvaluationResult`，包括 `low_quality_issues` 明细 |

当前不会写入 `evaluation_case_results`，因为入库质量评估不是按标准问题逐条执行。

因此，入库质量评估在数据库中体现为“一次任务一条 run，完整明细放在 detail_json”。这种设计保持了表结构简单，也符合当前评估粒度：它评估的是一个知识库版本或一个 chunk 数据集的整体质量，而不是逐条问答样本。

## 6. 检索评估

检索评估关注的是“用户问题进入检索链路后，系统是否能够召回预期的 FAQ 和知识库内容”。它从标准问题集出发，对每个问题执行真实或模拟检索，然后将召回结果与预先标注的 gold FAQ、gold rule 进行对比。

当前检索评估更准确地说是“端到端链路前半段评估”，因为它会从用户问题开始调用检索链路，但不评价最终 LLM 答案质量。它的主要价值是把召回问题定位清楚：是 FAQ 没命中，还是知识库文档没召回，还是正确内容排名靠后。

### 6.1 输入来源

检索评估依赖 `evaluation_cases` 中的标准问题。每条样本至少需要：

```json
{
  "case_id": "eval_0001",
  "question": "个人/个体店出售假冒商品怎么处理？",
  "expected_json": {
    "expected_faq_ids": ["faq_001"],
    "expected_rule_ids": ["923540006109319168"]
  }
}
```

评估样本的核心是 `question + expected_json`。`question` 表示用户可能提出的问题，`expected_json.expected_faq_ids` 表示期望命中的 FAQ，`expected_json.expected_rule_ids` 表示期望命中的知识库规则或文档。只要后续新增指标，仍然可以在 `expected_json` 中补充更多 gold 信息，而不必立即修改表结构。

### 6.2 执行链路

检索评估由 `run_retrieval_evaluation()` 编排：

```text
读取评估集
-> 校验评估集类型为 retrieval_eval 或 mixed
-> 读取 evaluation_cases
-> 构造 RetrievalEvalCase
-> mock_mode=true 时构造模拟 trace
-> mock_mode=false 时调用 retrieve_answer()
-> real_adapter 将 RetrievalResult 转为 RetrievalTrace
-> metrics.score_case() 计算单题指标
-> 写入 evaluation_case_results
-> 汇总写入 evaluation_runs.summary_json
```

执行过程可以概括为“标准问题集 -> 批量检索 -> 单题打分 -> 汇总指标 -> 结果落库”。每条 case 都会保留召回 trace，包括改写后的 query、FAQ 命中列表、知识库 chunk 命中列表和 debug 信息。这样评估结果不仅能给出总体分数，也能回看每道题为什么命中或为什么失败。

### 6.3 指标

当前只计算三个指标：

| 指标 | 字段 | 说明 |
| --- | --- | --- |
| FAQ Hit Rate@K | `faq_hit_at_k` / `faq_hit_rate_at_{k}` | FAQ TopK 命中任意 gold FAQ 记 1，否则记 0 |
| KB Recall@K | `kb_recall_at_k` / `kb_recall_at_{k}` | KB TopK 中命中的 gold rule_id 数 / gold rule_id 总数 |
| KB MRR@K | `kb_rr` / `kb_mrr_at_{k}` | 第一个命中 gold rule_id 的倒数排名 |

知识库指标按 `rule_id` 文档级计算。由于检索返回常是 chunk 级结果，评估前会按 `rule_id` 去重并保留首次出现顺序，避免多个 chunk 命中同一文档导致指标失真。

从业务含义上看，FAQ Hit Rate@K 适合衡量高频标准问答是否被快速命中；KB Recall@K 适合衡量知识库检索是否覆盖到正确文档；KB MRR@K 更关注正确文档是否排在前面。三者结合起来，既能看“有没有召回”，也能看“召回得够不够靠前”。

### 6.4 RAGAS 使用方式

`app/evaluation/retrieval/metrics.py` 已预留 RAGAS 支持：

| 指标 | 实现 |
| --- | --- |
| FAQ Hit Rate@K | RAGAS `numeric_metric` 自定义指标 |
| KB Recall@K | RAGAS `IDBasedContextRecall` |
| KB MRR@K | RAGAS `numeric_metric` 自定义指标 |

如果当前环境未安装 RAGAS，则自动使用本地手工汇总逻辑，保证工程链路可先跑通。

目前服务层 `run_retrieval_evaluation()` 单题评分调用的是 `score_case()`，汇总使用 `_summarize_retrieval_scores()`。`aggregate_scores_with_ragas()` 已存在，但还未接入服务层汇总路径。

因此当前 RAGAS 更像是“已预留、可切换”的指标框架。单题指标仍由本地逻辑计算，服务层汇总也使用本地聚合。后续如果希望在 PPT 中表达技术路线，可以说明：当前版本优先保证评估闭环稳定运行，后续再将服务层汇总切换到 RAGAS 统一计算。

## 7. 管理端接口

后端管理接口统一挂载在：

```text
/api/admin/evaluations
```

主要接口：

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/datasets` | GET | 查询评估集 |
| `/datasets` | POST | 创建评估集 |
| `/datasets/{dataset_id}` | DELETE | 删除评估集 |
| `/datasets/{dataset_id}/cases` | GET | 查询评估集样本 |
| `/datasets/{dataset_id}/cases/import` | POST | 批量导入样本 |
| `/ingestion-quality/runs` | POST | 执行入库质量评估并落库 |
| `/retrieval/runs` | POST | 执行检索评估并落库 |
| `/runs` | GET | 查询评估任务列表 |
| `/runs/{run_id}` | GET | 查询评估任务详情 |
| `/runs/{run_id}/cases` | GET | 查询检索评估单题结果 |
| `/chunk-quality/datasets` | GET | 查询临时 chunk 质量评估数据集 |
| `/chunk-quality/{dataset}` | GET | 直接执行临时 chunk 质量评估，不落库 |

说明：

- `/ingestion-quality/runs` 是当前页面使用的入库质量评估入口，会写入 `evaluation_runs`。
- `/chunk-quality/*` 是较早的直接评估接口，主要用于临时数据集验证，不写 4 表。
- `/retrieval/runs` 是当前页面使用的检索评估入口，会写入 `evaluation_runs` 和 `evaluation_case_results`。

从接口设计上看，当前模块已经把“调试接口”和“正式落库接口”区分开来。正式入口会创建评估任务并保存历史记录，适合页面展示和后续版本对比；临时接口主要用于快速验证数据集和算法逻辑，不参与统一任务管理。

## 8. 前端字段映射

前端在 `src/api/adminEvaluation.js` 中将后端 snake_case 字段映射为页面使用的 camelCase 字段。

前端字段映射的作用是把后端通用数据结构转换成页面更容易消费的展示模型。评估模块的页面显示主要依赖三类数据：评估集信息、评估任务摘要、单题评估详情。这里需要特别注意指标字段名，因为检索指标中的 K 值是动态的，字段名也会随配置变化。

### 8.1 评估集映射

| 后端字段 | 前端字段 |
| --- | --- |
| `dataset_id` | `datasetId` |
| `evaluation_type` | `type` |
| `sample_count` | `sampleCount` |
| `created_at` | `createdAt` |

### 8.2 评估任务映射

| 后端字段 | 前端字段 |
| --- | --- |
| `run_id` | `taskId` / `runId` |
| `evaluation_type` | `type` |
| `knowledge_base_version` | `kbVersion` |
| `config_json` | `config` |
| `summary_json` | `summary` |
| `detail_json` | `detail` |
| `metrics_text` | `metrics` |

检索评估页面依赖以下 summary 字段：

| 后端 summary 字段 | 前端显示 |
| --- | --- |
| `faq_hit_rate_at_5` | `FAQ Hit@5` |
| `kb_recall_at_10` | `KB Recall@10` |
| `kb_mrr_at_10` | `KB MRR@10` |
| `error_count` | 错误数 |

### 8.3 单题结果映射

| 后端字段 | 前端字段 |
| --- | --- |
| `case_id` | `caseId` |
| `retrieved_items_json.rewritten_query` | `rewrittenQuestion` |
| `expected_json.expected_rule_ids` | `expectedRuleId` |
| `expected_json.expected_faq_ids` | `expectedFaqId` |
| `metric_results_json.faq_hit_at_k` | `faqHit` |
| `metric_results_json.kb_recall_at_k` | `kbRecall` |
| `metric_results_json.kb_rr` | `kbRr` |
| `retrieved_items_json.faq_hits` | FAQ 召回详情 |
| `retrieved_items_json.kb_hits` | KB 召回详情 |

### 8.4 入库质量页面映射

入库质量页面通过 `run.detail` 和 `run.summary` 显示指标：

| 后端字段 | 前端显示 |
| --- | --- |
| `summary.chunk_count` 或 `detail.chunk_metrics.chunk_count` | 总 Chunk 数 |
| `summary.low_quality_issue_count` 或 `detail.chunk_metrics.low_quality_issue_count` | 低质量 Chunk |
| `summary.too_short_chunk_rate` 或 `detail.chunk_metrics.too_short_chunk_rate` | 过短率 |
| `summary.duplicate_group_count` 或 `detail.chunk_metrics.duplicate_group_count` | 重复率 |
| `detail.low_quality_issues` | 问题 Chunk 明细 |

## 9. 当前需要统一或注意的点

当前评估模块已经形成基本闭环，但仍有几处实现口径需要统一。这些问题不影响主流程跑通，但会影响页面展示准确性、指标解释一致性和后续扩展清晰度。建议在后续迭代中优先处理这些“小错位”，再继续扩展更复杂的端到端答案评估。

### 9.1 评估类型命名

当前实现已经区分：

```text
ingestion_quality
retrieval_eval
end_to_end
mixed
```

建议继续保持该口径。当前已实现的不是完整端到端评估，不应在文档或页面中混称为端到端评估。

### 9.2 RAGAS 汇总路径

`metrics.py` 中有 `aggregate_scores_with_ragas()`，但 `services/evaluation.py` 当前汇总使用 `_summarize_retrieval_scores()` 本地逻辑。

后续如果要求“正式采用 RAGAS 作为汇总计算框架”，需要在 `run_retrieval_evaluation()` 中改为：

```text
收集 cases + traces
-> 调 aggregate_scores_with_ragas()
-> 写入 evaluation_runs.summary_json
```

单题结果仍建议保留 `score_case()` 本地计算，方便页面展示和问题排查。

### 9.3 入库质量评估的 duplicate_threshold

前端和 schema 中有 `duplicate_threshold`，但当前 `runner.py` 的重复判断使用完全相同正文 hash，没有使用相似度阈值。

如果后续要支持“相似重复”，需要补充：

```text
duplicate_threshold -> 相似度计算 -> duplicate_content 或 similar_content
```

否则页面输入“重复阈值 0.95”会和后端实际行为不完全一致。

### 9.4 入库质量评估 dataset_id

`run_ingestion_quality_evaluation()` 当前落库时 `dataset_id=None`。如果希望历史记录能区分 enterprise/personal 临时数据集，或区分不同真实来源，可以考虑后续将：

```text
payload.dataset 或 knowledge_base_version
```

写入 `evaluation_runs.dataset_id` 或 `config_json` 中。当前 `config_json` 已保存完整 payload，短期可接受。

### 9.5 前端评估记录类型过滤

前端 `recordQuery.type` 当前选项值是：

```text
retrieval
ingestion
```

但后端 `evaluation_type` 使用：

```text
retrieval_eval
ingestion_quality
```

这会导致记录筛选可能不生效。建议前端选项值统一改为后端真实枚举。

### 9.6 检索评估 TopK 展示固定为 5/10

前端 `mapRun()` 当前固定读取：

```text
faq_hit_rate_at_5
kb_recall_at_10
kb_mrr_at_10
```

如果用户在页面输入了非默认 K 值，summary 字段会变成：

```text
faq_hit_rate_at_{faq_top_k}
kb_recall_at_{kb_top_k}
kb_mrr_at_{kb_top_k}
```

这里有两处需要统一：

| 位置 | 当前问题 | 建议 |
| --- | --- | --- |
| 前端 `src/api/adminEvaluation.js` 的 `mapRun()` | 固定读取 `faq_hit_rate_at_5`、`kb_recall_at_10`、`kb_mrr_at_10` | 根据 `config.faq_top_k` 和 `config.kb_top_k` 动态拼接 summary 字段 |
| 后端 `app/services/evaluation.py` 的 `_metrics_text()` | 固定按 `FAQ Hit@5`、`KB Recall@10`、`MRR@10` 生成摘要文案 | 根据 summary 中实际存在的指标字段生成文案，或基于 `config_json` 生成动态标签 |

否则用户输入非默认 K 值时，评估结果本身已经正确写入 `summary_json`，但列表摘要和前端指标卡可能显示为空或仍显示旧的 5/10 标签。

## 10. 建议后的整体数据流

整体数据流可以理解为两条独立但共享任务表的链路。入库质量评估面向知识库版本本身，输出 chunk 质量指标；检索评估面向标准问题集，输出 FAQ 和知识库召回指标。两条链路最终都写入 `evaluation_runs`，使前端可以用统一的评估记录页面展示历史任务。

### 10.1 入库质量评估数据流

```text
前端选择知识库版本和阈值
-> POST /api/admin/evaluations/ingestion-quality/runs
-> services/evaluation.run_ingestion_quality_evaluation()
-> 有 kb_version：从 Milvus 读取 chunk
-> 无 kb_version：读取临时 JSON 数据集
-> ingestion_quality.runner 计算指标
-> evaluation_runs.summary_json 保存汇总
-> evaluation_runs.detail_json 保存完整明细
-> 前端展示总 Chunk、低质量 Chunk、过短率、重复率和问题 chunk 明细
```

### 10.2 检索评估数据流

```text
前端选择评估集、知识库版本、FAQ TopK、KB TopK
-> POST /api/admin/evaluations/retrieval/runs
-> services/evaluation.run_retrieval_evaluation()
-> 读取 evaluation_cases
-> 每条 case 转 RetrievalEvalCase
-> mock_mode=false 时调用 retrieve_answer()
-> real_adapter 转 RetrievalTrace
-> metrics.score_case() 计算单题分
-> evaluation_case_results 保存单题 trace 和指标
-> evaluation_runs.summary_json 保存汇总
-> 前端展示 run 级指标和单题召回详情
```

## 11. 后续扩展方向

后续扩展应继续沿用当前 4 表基础结构，优先在 JSON 字段中增加配置、指标和明细，避免过早拆分大量指标表。只有当某类明细数据需要频繁分页查询、筛选、统计或单独维护时，再考虑拆表。

| 方向 | 建议 |
| --- | --- |
| 真正端到端评估 | 复用 `evaluation_runs` 和 `evaluation_case_results`，在 `actual_answer` 中保存模型答案，在 `metric_results_json` 中增加答案正确性、忠实性、引用准确性等指标 |
| RAGAS 正式汇总 | 将 `aggregate_scores_with_ragas()` 接入服务层汇总路径 |
| 评估集来源管理 | 如需管理 seed 文件路径，可给 `evaluation_datasets` 增加 `source_config_json`，当前表尚未包含 |
| 入库质量历史对比 | 可以基于 `evaluation_runs.summary_json` 做版本对比，无需新增表 |
| 问题 chunk 明细查询 | 当前存在 `detail_json.low_quality_issues` 中，数据量大时可拆表；第一版不建议拆 |

## 12. PPT 内容页提炼建议

如果基于本文档生成 PPT，可以将评估模块拆成以下几页内容。每页建议突出一个核心观点，避免把所有表结构和接口细节堆到同一页。

| PPT 页面 | 推荐标题 | 页面重点 |
| --- | --- | --- |
| 1 | 评估模块定位 | 当前模块围绕入库质量和检索效果两类核心问题展开，端到端答案评估作为后续扩展方向 |
| 2 | 评估模块整体架构 | 后端采用接口层、服务编排层、评估算法层、数据模型层；前端提供评估集、入库评估、检索评估、评估记录四个入口 |
| 3 | 入库质量评估流程 | 从临时 JSON 或 Milvus 读取 chunk，计算空 chunk、过短、过长、重复、低唯一字符比例等问题，结果写入 `evaluation_runs` |
| 4 | 检索评估流程 | 以标准问题集为输入，批量调用检索链路，对 FAQ 和知识库召回结果计算 Hit Rate、Recall、MRR，并保存单题 trace |
| 5 | 数据库最小闭环 | 通过 `evaluation_datasets`、`evaluation_cases`、`evaluation_runs`、`evaluation_case_results` 四张表支撑评估集、样本、任务、单题结果 |
| 6 | 当前实现状态与待统一点 | 已实现管理端闭环和基础指标；需统一评估类型枚举、动态 TopK 展示、RAGAS 汇总路径和重复阈值语义 |
| 7 | 后续演进方向 | 在现有表结构上扩展真正端到端评估、答案质量评分、引用准确性、版本对比和上线前回归 |

适合在 PPT 中使用的一句话总结：

```text
评估模块当前已经形成“标准评估集/知识库版本 -> 批量执行 -> 指标计算 -> 结果落库 -> 前端查看与追溯”的基础闭环，为后续 RAG 效果优化、版本对比和上线前回归提供了统一入口。
```
