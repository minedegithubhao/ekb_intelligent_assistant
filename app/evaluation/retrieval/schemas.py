"""检索评估内部数据结构。

这里放的是评估模块内部流转对象，而不是 HTTP 请求/响应模型。
这样做有两个好处：

1. 评估逻辑不用依赖 FastAPI 或接口层结构；
2. 将来如果项目接口字段改名，只需要调整 adapter，不用重写 scorer/runner。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FAQHit:
    """一次 FAQ 检索命中的简化结果。

    当前三个指标里，FAQ 侧只需要判断：
    - 命中了哪个 FAQ；
    - 它排在第几；
    - 分数大概是多少。

    所以这里不保留完整 FAQ 对象，只保留评估真正需要的字段。
    """

    faq_id: str
    rank: int
    score: float | None = None
    question: str | None = None


@dataclass(frozen=True)
class KBHit:
    """一次知识库检索命中的简化结果。

    这里同时保留 `rule_id` 和 `chunk_id`，因为：

    - 评估指标按文档/规则级计算，主键通常是 `rule_id`；
    - 但排查问题时，经常还需要看到具体是哪个 chunk 命中的；
    - 所以内部对象里两者都保留，后续由 scorer 决定使用哪一层。
    """

    rule_id: str
    chunk_id: str | None
    rank: int
    score: float | None = None
    title: str | None = None
    chunk_text_preview: str | None = None


@dataclass(frozen=True)
class RetrievalEvalCase:
    """检索评估样本。

    这里只保留当前三个指标真正需要的字段：

    - `question`：要送进生产检索链路的问题；
    - `expected_faq_ids`：FAQ 命中 gold；
    - `expected_rule_ids`：知识库命中 gold；
    - 其余是为了复用生产隔离条件和版本条件。
    """

    case_id: str
    question: str
    expected_faq_ids: list[str] = field(default_factory=list)
    expected_rule_ids: list[str] = field(default_factory=list)
    scenario_id: str | None = None
    source_filter: str | None = None
    tenant_id: str | None = None
    dataset_id: str | None = None
    visibility: str | None = None
    user_role: str | None = None
    kb_version: str | None = None


@dataclass
class RetrievalTrace:
    """一条样本执行生产检索链路后的 trace。

    这个对象是 adapter 层和 scorer 层之间的契约，目的是把外部服务的原始 payload
    收敛成稳定结构，避免下游反复读原始 dict。
    """

    case_id: str
    question: str
    rewritten_query: str
    faq_hits: list[FAQHit] = field(default_factory=list)
    kb_hits: list[KBHit] = field(default_factory=list)
    raw_debug_payload: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class RetrievalCaseScore:
    """单条样本的评分结果。

    当前只计算三个检索指标，因此对象结构非常聚焦：

    - `faq_hit_at_k`
    - `kb_recall_at_k`
    - `kb_rr`

    同时把 rewrite 结果和原始 hits 一起保留下来，方便后续直接写 rows 报告。
    """

    case_id: str
    question: str
    expected_faq_ids: list[str] = field(default_factory=list)
    expected_rule_ids: list[str] = field(default_factory=list)
    faq_hit_at_k: float | None = None
    kb_recall_at_k: float | None = None
    kb_rr: float | None = None
    rewritten_query: str = ""
    faq_hits: list[dict[str, Any]] = field(default_factory=list)
    kb_hits: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


@dataclass(frozen=True)
class RetrievalEvalConfig:
    """检索评估运行配置。

    把配置集中成对象有两个目的：

    1. runner 和 scorer 可以共享同一套 K 值和过滤条件；
    2. 后续如果要把配置落库或写入报告，不需要再手动拼字典。
    """

    faq_top_k: int = 5
    kb_top_k: int = 10
    faq_hit_threshold: float = 1.0
    kb_recall_threshold: float = 1.0
    kb_mrr_threshold: float = 1.0
    scenario_id: str | None = None
    tenant_id: str | None = None
    dataset_id: str | None = None
    visibility: str | None = None
    user_role: str | None = None
    kb_version: str | None = None
