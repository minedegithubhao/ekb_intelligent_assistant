# 检索函数评估调用说明

评估功能可以直接调用 `app.services.retrieval.retrieve_answer`。这个函数同时兼容两种场景：

- 用户提问接口：不传覆盖参数，自动使用 MySQL 当前 active 知识库版本和当前启用热参数。
- 评估任务：显式传入热参数覆盖值和知识库版本，执行一次定制化检索。

## 用户提问接口默认用法

```python
from app.services.retrieval import retrieve_answer

result = retrieve_answer(
    db,
    question="用户问题",
    knowledge_base_type="enterprise",  # enterprise / personal
    history_messages=history_messages,
)
```

默认行为：

- 热参数从 `retrieval_hot_configs` 当前启用配置读取。
- 知识库版本从 `kb_version_pointers` / `kb_versions` 当前 active 版本读取。
- 检索时 Milvus 过滤条件为 `kb_version + source`。
- LLM 变体生成、追问改写、最终回答生成走默认 qwen-max 配置。

## 评估定制用法

```python
from app.services.retrieval import retrieve_answer

result = retrieve_answer(
    db,
    question="怎么申请退货？",
    knowledge_base_type="enterprise",
    kb_version="kb_20260623120000",
    hot_config_overrides={
        "llm_variant_count": 3,
        "faq_candidate_limit_per_query": 30,
        "faq_fusion_top_k": 20,
        "faq_rerank_top_k": 5,
        "doc_candidate_limit_per_query": 80,
        "doc_fusion_top_k": 30,
        "doc_rerank_top_k": 8,
        "final_evidence_top_k": 8,
    },
)
```

说明：

- `kb_version` 会从 MySQL `kb_versions` 查询对应 `faq_collection_name` 和 `doc_collection_name`。
- 评估指定版本不要求该版本必须是 active，但该版本必须存在 collection 名称。
- `hot_config_overrides` 只需要传要覆盖的字段，未传字段继续使用 MySQL 当前热参数。
- 覆盖字段会经过 `RetrievalHotConfigValues` 校验，例如权重和必须等于 1、rerank top-k 不能大于 fusion top-k。
- 不支持旧字段 `query_variant_total`，LLM 变体数量只使用 `llm_variant_count`。

## 返回结果

`retrieve_answer` 返回 `RetrievalResult`：

```python
result.answer          # 最终回答文本
result.hit_type        # rule_greeting / faq_high / faq_middle_doc / doc / none 等
result.sources         # 给前端展示的简化来源
result.faq_evidence    # FAQ rerank 后证据
result.doc_evidence    # 文档 rerank 后证据
result.final_evidence  # 最终交给 LLM 生成答案的完整证据
result.debug           # 调试信息，包括 query variants、hot config、知识库版本
```

评估同学重点看 `result.final_evidence`。它保留了最终送给 LLM 的完整 evidence item：

```python
for item in result.final_evidence:
    print(item.source_type)
    print(item.evidence_id)
    print(item.text)
    print(item.parent_content)
    print(item.answer)
    print(item.score)
    print(item.confidence)
    print(item.source_doc_id)
    print(item.reference_source)
    print(item.title)
    print(item.metadata)
```

## 直接传入知识库版本对象

如果评估侧已经自己查好了版本对象，也可以直接传 `knowledge_base`，避免函数再查一次 MySQL：

```python
from app.schemas.retrieval import ActiveKnowledgeVersion
from app.services.retrieval import retrieve_answer

result = retrieve_answer(
    db,
    question="怎么申请退货？",
    knowledge_base_type="enterprise",
    knowledge_base=ActiveKnowledgeVersion(
        kb_version="kb_20260623120000",
        faq_collection_name="kb_20260623120000_faq",
        doc_collection_name="kb_20260623120000_doc",
        status="staged",
    ),
    hot_config_overrides={"llm_variant_count": 2},
)
```

如果同时传 `kb_version` 和 `knowledge_base`，两者的版本号必须一致。
