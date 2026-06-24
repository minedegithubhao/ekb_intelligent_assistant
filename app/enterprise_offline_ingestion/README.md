# Enterprise Offline Ingestion

企业级 RAG 离线入库模块。

本目录只负责离线预处理、切分、向量化和 Milvus 写入能力，不自动挂载 FastAPI 路由，也不直接修改现有业务入口。

## 模块职责

当前离线入库流程包括：

1. 读取并校验 `index.csv`
2. 清洗 Markdown 文档
3. 过滤文档开头规则元信息块
4. 生成 parent-child chunk
5. 将 Markdown 表格按行切分
6. 读取并清洗 FAQ CSV
7. 生成 dense 向量
8. 写入 Milvus DOC / FAQ collection

## 当前 Milvus 设计

当前代码里的 collection 设计已经对齐为：

```text
pk
text
dense
sparse
$meta (dynamic field)
```

说明：

- `pk`：主键字段
- `text`：主文本字段
- `dense`：稠密向量字段
- `sparse`：Milvus built-in BM25 function 输出字段
- 其余业务字段全部通过 dynamic field 写入

### DOC / FAQ 的公共显式字段

```text
pk      -> 主键
text    -> 主检索文本
dense   -> FloatVector(1024)
sparse  -> SparseFloatVector
```

### Dynamic field 中的业务字段

DOC 常见动态字段：

```text
child_chunk_id
parent_id
source_doc_id
title
title_path
summary
scope
scope_name
reference_source
rule_id
created
modified
active_time
update_time
label_names
label_list
json_path
markdown_path
file_name
chunk_type
chunk_order
record_type
parent_content
```

FAQ 常见动态字段：

```text
faq_id
answer
source
reference_source
category
tags
tag_list
doc_refs
doc_ref_ids
file_name
row_number
record_type
```

### 稀疏向量生成方式

当前 schema 使用 Milvus built-in BM25 function：

```text
text -> sparse
```

也就是说：

- `dense` 由本地 embedding provider 生成
- `sparse` 不再依赖业务侧手工写入
- `sparse` 由 Milvus 基于 `text` 自动生成

### 当前索引设计

```text
dense  -> AUTOINDEX(L2)
sparse -> AUTOINDEX(BM25)
```

## 路径配置原则

代码中不写死个人本地绝对路径。

默认数据目录使用项目根目录下的相对路径：

```text
source_data
```

如果不同环境的数据目录不一致，通过环境变量覆盖：

```powershell
$env:KNOWFORGE_SOURCE_DATA_ROOT="E:/your/path/source_data"
```

## 环境变量

离线入库相关环境变量：

```text
KNOWFORGE_SOURCE_DATA_ROOT
KNOWFORGE_CLEAN_MARKDOWN_DIR
KNOWFORGE_INDEX_CSV_NAME
KNOWFORGE_FAQ_CSV_DIR
KNOWFORGE_DOC_PARENT_CHUNK_SIZE
KNOWFORGE_DOC_CHILD_CHUNK_SIZE
KNOWFORGE_DOC_CHILD_CHUNK_OVERLAP
KNOWFORGE_TABLE_SPLIT_STRATEGY
KNOWFORGE_TABLE_HEADER_REQUIRED
KNOWFORGE_TABLE_ROW_MAX_CHARS
KNOWFORGE_DOC_COLLECTION_NAME
KNOWFORGE_FAQ_COLLECTION_NAME
KNOWFORGE_DENSE_VECTOR_DIM
KNOWFORGE_SPARSE_VECTOR_ENABLED
KNOWFORGE_EMBEDDING_BATCH_SIZE
KNOWFORGE_MILVUS_INSERT_BATCH_SIZE
KNOWFORGE_STRICT_INDEX_MATCH
KNOWFORGE_FAQ_REFERENCE_REQUIRED
KNOWFORGE_MILVUS_DB_NAME
```

说明：

- `KNOWFORGE_MILVUS_DB_NAME` 可临时覆盖目标 Milvus 数据库
- 当前默认数据库配置来自 `config/app.yaml`

## 文件说明

```text
settings.py        离线入库配置项
models.py          核心数据结构
index_reader.py    读取并校验 index.csv
cleaner.py         Markdown / FAQ 清洗规则
splitter.py        parent-child 切分和表格按行切分
vectorization.py   向量化接口和向量行构建
bge_m3_provider.py 本地 bge-m3 适配器
milvus_writer.py   Milvus collection 创建、schema 和写入
pipeline.py        离线入库编排
factory.py         默认向量化服务 / pipeline 组装入口
```

## scripts/enterprise_offline_ingestion

当前已有脚本：

```text
001_init_offline_ingestion_config.sql
export_chunk_json.py
run_dev_sample_ingestion.py
run_full_document_ingestion.py
run_full_ingestion_batched.py
```

用途说明：

- `export_chunk_json.py`
  - 只做清洗 + 切分
  - 导出 4 个 JSON 文件到 `source_data/offline_chunk_json_exports`

- `run_dev_sample_ingestion.py`
  - 用少量样本验证当前 Milvus schema
  - 会创建调试 collection：
    - `doc_collection_dev_sample`
    - `faq_collection_dev_sample`

- `run_full_document_ingestion.py`
  - 全量文档入库脚本
  - 一次性跑完整批

- `run_full_ingestion_batched.py`
  - 全量分批入库脚本
  - 更适合大批量文档场景

## index.csv 字段映射

当前依赖 `index.csv` 中的字段：

```text
rule_id
scope
title
summary
created
modified
active_time
label_names
source_url
json_path
markdown_path
```

字段用途：

```text
rule_id       -> source_doc_id
scope         -> scope / scope_name
title         -> title
summary       -> summary
source_url    -> reference_source
json_path     -> dynamic field
markdown_path -> dynamic field
```

当前支持的 `scope`：

```text
enterprise = 企业
personal_individual = 个人/个体
```

## 清洗规则

文档开头的规则元信息块会从正文中删除：

```text
rule_id
source_url
label_names
active_time
update_time
```

这些字段不会进入正文检索文本，但会保留到 metadata / dynamic field 中。

同时：

- Markdown / HTML 链接会保留锚文本，去掉 URL
- 多余空行会被压缩
- FAQ 中 `question` / `answer` 不能为空
- FAQ 中 `reference_source` 可按配置要求为必填

## 表格切分规则

Markdown 表格只按行切分。

表格行会被转换成：

```text
表头1=值1；表头2=值2；表头3=值3
```

当前不做：

```text
整表回填
复杂表格结构建模
跨表上下文补充
```

## 向量化设计

### 默认工厂模式

`factory.py` 中的默认实现：

- dense provider：本地 `BGEM3EmbeddingProvider`
- sparse provider：同一个 `BGEM3EmbeddingProvider`

这意味着默认工厂仍然保留“本地模型也能产 sparse”的能力。

### 当前 Milvus writer 行为

`milvus_writer.py` 当前实际写库时：

- 显式写入 `pk`
- 显式写入 `text`
- 显式写入 `dense`
- 不手工写入 `sparse`
- 依赖 Milvus built-in BM25 function 生成 `sparse`
- 业务字段全部展开到 dynamic field

## 使用入口

### 只准备数据，不写 Milvus

```python
from pathlib import Path

from app.enterprise_offline_ingestion import IngestionSettings, OfflineIngestionPipeline

settings = IngestionSettings()
pipeline = OfflineIngestionPipeline(settings)

batch = pipeline.prepare(
    markdown_paths=[Path("path/to/rule.md")],
    faq_paths=[],
)
```

### 使用默认本地向量化服务和 Milvus writer

```python
from app.enterprise_offline_ingestion import build_default_offline_ingestion_pipeline

pipeline = build_default_offline_ingestion_pipeline()
pipeline.ingest(
    markdown_paths=[],
    faq_paths=[],
)
```

## 调试与验证

当前已验证的能力包括：

- 严格索引匹配
- 分批向量化
- 写入前幂等删除
- dynamic field schema
- Milvus built-in BM25 function schema
- dense / sparse index 创建

## 注意事项

- 本模块不会自动执行入库。
- 本模块不会自动修改已有 FastAPI 路由。
- 真实入库前需要确认 Milvus 服务可用。
- 如果使用 `BGEM3EmbeddingProvider`，需要安装 `FlagEmbedding` 及相关推理依赖。
- 如果使用调试脚本里的本地 dense provider，则只依赖 `torch + transformers`。
- 当前全量脚本较重，推荐优先使用分批脚本。
