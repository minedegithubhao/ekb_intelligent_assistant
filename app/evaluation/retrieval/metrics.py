"""基于 Ragas 的检索指标计算。

当前模块只负责三个指标：

- FAQ Hit Rate@K
- 知识库 Recall@K
- 知识库 MRR

其中：
- FAQ Hit Rate@K：Ragas 没有现成指标，使用自定义 numeric_metric；
- 知识库 Recall@K：使用 Ragas 内置 IDBasedContextRecall；
- 知识库 MRR：使用自定义 numeric_metric。
"""

from __future__ import annotations

from dataclasses import asdict

try:
    # 正式环境优先使用真实 Ragas。
    from ragas import SingleTurnSample, evaluate
    from ragas.dataset_schema import EvaluationDataset
    from ragas.metrics import IDBasedContextRecall, numeric_metric

    RAGAS_AVAILABLE = True
except ImportError:
    # 当前工作区没有安装 ragas 时，评估模块仍然可以用本地回退逻辑先跑通链路。
    # 这样你可以先验证：
    # - 数据格式是否正确；
    # - 指标计算逻辑是否正确；
    # - 报告结构是否符合预期。
    #
    # 真实项目联调时，仍然建议安装 ragas 并走正式实现。
    RAGAS_AVAILABLE = False
    SingleTurnSample = None
    EvaluationDataset = None
    IDBasedContextRecall = None
    evaluate = None
    numeric_metric = None

from app.evaluation.retrieval.schemas import (
    RetrievalCaseScore,
    RetrievalEvalCase,
    RetrievalEvalConfig,
    RetrievalTrace,
)


def dedupe_keep_order(items: list[str]) -> list[str]:
    """对列表去重，但保留第一次出现顺序。

    这个函数在知识库指标里非常关键，因为：

    - 检索返回通常是 chunk 级结果；
    - 当前 Recall/MRR 按 rule_id 文档级计算；
    - 同一个 rule_id 可能对应多个 chunk；

    如果不去重，文档级指标会被重复 chunk 干扰，导致结果失真。
    """
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def make_faq_hit_rate_metric(k: int):
    """创建 FAQ Hit Rate@K 指标。

    规则很简单：
    - FAQ TopK 中只要命中任意一个 gold FAQ，就记 1；
    - 否则记 0。
    """
    if not RAGAS_AVAILABLE:
        raise RuntimeError("当前环境未安装 ragas，不能创建 FAQ 自定义 Ragas 指标。")

    @numeric_metric(name=f"faq_hit_rate_at_{k}", allowed_values=(0.0, 1.0))
    def faq_hit_rate(retrieved_context_ids: list[str], reference_context_ids: list[str]) -> float:
        retrieved = set((retrieved_context_ids or [])[:k])
        gold = set(reference_context_ids or [])
        return 1.0 if retrieved & gold else 0.0

    return faq_hit_rate


def make_kb_mrr_metric(k: int):
    """创建知识库 MRR@K 指标。

    MRR 计算规则：
    - 在前 K 个文档级 rule_id 结果中，从前往后寻找第一个命中 gold 的结果；
    - 命中第 1 名就是 1.0；
    - 命中第 2 名就是 0.5；
    - 以此类推；
    - 如果前 K 都没有命中，则为 0。
    """
    if not RAGAS_AVAILABLE:
        raise RuntimeError("当前环境未安装 ragas，不能创建 KB MRR Ragas 指标。")

    @numeric_metric(name=f"kb_mrr_at_{k}", allowed_values=(0.0, 1.0))
    def kb_mrr(retrieved_context_ids: list[str], reference_context_ids: list[str]) -> float:
        gold = set(reference_context_ids or [])
        for rank, doc_id in enumerate((retrieved_context_ids or [])[:k], start=1):
            if doc_id in gold:
                return 1.0 / rank
        return 0.0

    return kb_mrr


def _build_faq_dataset(
    cases: list[RetrievalEvalCase],
    traces: list[RetrievalTrace],
    k: int,
) -> EvaluationDataset:
    """构建 FAQ 评估数据集。

    FAQ 指标只依赖：
    - `retrieved_context_ids`：FAQ TopK 的 faq_id 列表；
    - `reference_context_ids`：gold faq_id 列表。
    """
    if not RAGAS_AVAILABLE:
        raise RuntimeError("当前环境未安装 ragas，不能构建 Ragas FAQ 数据集。")

    samples: list[SingleTurnSample] = []

    for case, trace in zip(cases, traces):
        if not case.expected_faq_ids:
            # 没有 FAQ gold 的样本不参与 FAQ 指标计算。
            continue

        faq_topk_ids = [item.faq_id for item in trace.faq_hits[:k]]
        samples.append(
            SingleTurnSample(
                user_input=case.question,
                retrieved_context_ids=faq_topk_ids,
                reference_context_ids=case.expected_faq_ids,
            )
        )

    return EvaluationDataset(samples=samples, name=f"faq_eval_k{k}")


def _build_kb_dataset(
    cases: list[RetrievalEvalCase],
    traces: list[RetrievalTrace],
    k: int,
) -> EvaluationDataset:
    """构建知识库评估数据集。

    文档级评估要点：
    - 原始命中是 chunk 级；
    - 评估时先提取 rule_id；
    - 再按 rule_id 去重并保留原始出现顺序；
    - 最终截取前 K 个 rule_id 作为 retrieved_context_ids。
    """
    if not RAGAS_AVAILABLE:
        raise RuntimeError("当前环境未安装 ragas，不能构建 Ragas KB 数据集。")

    samples: list[SingleTurnSample] = []

    for case, trace in zip(cases, traces):
        if not case.expected_rule_ids:
            # 没有 KB gold 的样本不参与 KB 指标计算。
            continue

        raw_rule_ids = [item.rule_id for item in trace.kb_hits]
        topk_rule_ids = dedupe_keep_order(raw_rule_ids)[:k]
        samples.append(
            SingleTurnSample(
                user_input=case.question,
                retrieved_context_ids=topk_rule_ids,
                reference_context_ids=case.expected_rule_ids,
            )
        )

    return EvaluationDataset(samples=samples, name=f"kb_eval_k{k}")


def score_case(
    case: RetrievalEvalCase,
    trace: RetrievalTrace,
    config: RetrievalEvalConfig,
) -> RetrievalCaseScore:
    """计算单条样本的三个指标。

    为什么这里还要单独算一次，而不是只依赖 Ragas 汇总结果：

    - Ragas 适合做整体统计；
    - 但工程排查必须保留单题分数；
    - 所以单题分数在这里直接按业务规则计算，后续写进 `rows`。
    """
    faq_hit_at_k: float | None = None
    kb_recall_at_k: float | None = None
    kb_rr: float | None = None

    if case.expected_faq_ids:
        gold_faq_ids = set(case.expected_faq_ids)
        retrieved_faq_ids = {item.faq_id for item in trace.faq_hits[: config.faq_top_k]}
        faq_hit_at_k = 1.0 if gold_faq_ids & retrieved_faq_ids else 0.0

    if case.expected_rule_ids:
        gold_rule_ids = set(case.expected_rule_ids)
        raw_rule_ids = [item.rule_id for item in trace.kb_hits]
        topk_rule_ids = dedupe_keep_order(raw_rule_ids)[: config.kb_top_k]

        kb_recall_at_k = len(gold_rule_ids & set(topk_rule_ids)) / len(gold_rule_ids)

        kb_rr = 0.0
        for rank, rule_id in enumerate(topk_rule_ids, start=1):
            if rule_id in gold_rule_ids:
                kb_rr = 1.0 / rank
                break

    return RetrievalCaseScore(
        case_id=case.case_id,
        question=case.question,
        expected_faq_ids=case.expected_faq_ids,
        expected_rule_ids=case.expected_rule_ids,
        faq_hit_at_k=faq_hit_at_k,
        kb_recall_at_k=kb_recall_at_k,
        kb_rr=kb_rr,
        rewritten_query=trace.rewritten_query,
        faq_hits=[asdict(item) for item in trace.faq_hits],
        kb_hits=[asdict(item) for item in trace.kb_hits],
        error=trace.error,
    )


def aggregate_scores_with_ragas(
    cases: list[RetrievalEvalCase],
    traces: list[RetrievalTrace],
    config: RetrievalEvalConfig,
) -> dict:
    """使用 Ragas 计算整体指标。

    FAQ 和 KB 分成两套 dataset 的原因是：
    - FAQ gold 和 KB gold 不是同一类 ID；
    - 混在同一套 sample 里容易把字段语义搞乱；
    - 分开构建后，逻辑更清晰，也更容易排错。
    """
    if not RAGAS_AVAILABLE:
        # 没有 ragas 依赖时，使用本地手工汇总逻辑。
        # 这样可以先验证工程可行性和代码是否能正常使用，
        # 等接入真实项目或安装 ragas 后，再切回正式实现。
        faq_scores = []
        kb_recall_scores = []
        kb_mrr_scores = []

        for case, trace in zip(cases, traces):
            case_score = score_case(case, trace, config)
            if case_score.faq_hit_at_k is not None:
                faq_scores.append(case_score.faq_hit_at_k)
            if case_score.kb_recall_at_k is not None:
                kb_recall_scores.append(case_score.kb_recall_at_k)
            if case_score.kb_rr is not None:
                kb_mrr_scores.append(case_score.kb_rr)

        return {
            "ragas_backend": "manual_fallback",
            "faq_case_count": len(faq_scores),
            "kb_case_count": len(kb_recall_scores),
            f"faq_hit_rate_at_{config.faq_top_k}": (
                round(sum(faq_scores) / len(faq_scores), 4) if faq_scores else None
            ),
            f"kb_recall_at_{config.kb_top_k}": (
                round(sum(kb_recall_scores) / len(kb_recall_scores), 4) if kb_recall_scores else None
            ),
            f"kb_mrr_at_{config.kb_top_k}": (
                round(sum(kb_mrr_scores) / len(kb_mrr_scores), 4) if kb_mrr_scores else None
            ),
        }

    faq_metric = make_faq_hit_rate_metric(config.faq_top_k)
    kb_recall_metric = IDBasedContextRecall()
    kb_mrr_metric = make_kb_mrr_metric(config.kb_top_k)

    faq_dataset = _build_faq_dataset(cases, traces, config.faq_top_k)
    kb_dataset = _build_kb_dataset(cases, traces, config.kb_top_k)

    faq_result = evaluate(faq_dataset, metrics=[faq_metric]) if faq_dataset.samples else None
    kb_result = evaluate(kb_dataset, metrics=[kb_recall_metric, kb_mrr_metric]) if kb_dataset.samples else None

    faq_df = faq_result.to_pandas() if faq_result else None
    kb_df = kb_result.to_pandas() if kb_result else None

    faq_col = f"faq_hit_rate_at_{config.faq_top_k}"
    mrr_col = f"kb_mrr_at_{config.kb_top_k}"

    recall_value = None
    if kb_df is not None and len(kb_df):
        # Ragas 内置 recall 指标列名不同版本可能略有差异，
        # 这里按包含 recall 的列名动态查找，减少版本升级带来的脆弱性。
        recall_col = [col for col in kb_df.columns if "recall" in col.lower()][0]
        recall_value = float(kb_df[recall_col].mean())

    return {
        "ragas_backend": "ragas",
        "faq_case_count": int(len(faq_df)) if faq_df is not None else 0,
        "kb_case_count": int(len(kb_df)) if kb_df is not None else 0,
        faq_col: float(faq_df[faq_col].mean()) if faq_df is not None and len(faq_df) else None,
        f"kb_recall_at_{config.kb_top_k}": recall_value,
        mrr_col: float(kb_df[mrr_col].mean()) if kb_df is not None and len(kb_df) else None,
    }
