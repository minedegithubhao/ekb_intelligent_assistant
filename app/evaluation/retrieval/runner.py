"""检索评估执行器。

这个模块负责把以下几件事串起来：

1. 读取评估集；
2. 把样本转换成内部评估对象；
3. 调用生产检索链路 `debug_retrieval()`；
4. 把原始 payload 转成统一 trace；
5. 计算单题分数和整体指标；
6. 组装最终报告对象。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from typing import Any

from app.evaluation.common.dataset_loader import EvalCaseRuntime, load_eval_items
from app.evaluation.retrieval.metrics import aggregate_scores_with_ragas, score_case
from app.evaluation.retrieval.schemas import (
    RetrievalEvalCase,
    RetrievalEvalConfig,
)
from app.evaluation.retrieval.trace_adapter import build_retrieval_trace


def get_qa_service() -> Any:
    """Return the project retrieval service once it is wired into this repo.

    The retrieval evaluation code was imported from a reference project that
    exposed ``qa_core.application.factory.get_qa_service``. This repository does
    not currently have that service entry point, so keep the dependency lazy and
    explicit until the retrieval adapter is connected in the next step.
    """
    raise RuntimeError(
        "retrieval evaluation is not wired to the current project's retrieval service yet"
    )


def build_eval_case(item: dict[str, Any], index: int, args: argparse.Namespace) -> RetrievalEvalCase:
    """把原始评估样本转换成检索评估内部对象。

    这里兼容两类常见评估集格式：

    1. 扁平结构：
       - expected_faq_ids
       - expected_rule_ids

    2. 嵌套结构：
       - expected_faq: [{faq_id: ...}]
       - expected_docs: [{rule_id: ...}]

    这样你可以先接当前数据集，不需要强制重构评估文件格式。
    """
    runtime = EvalCaseRuntime.from_item(item, index, args, session_prefix="retrieval-eval")

    if item.get("expected_faq_ids") is not None:
        expected_faq_ids = [
            str(value).strip()
            for value in list(item.get("expected_faq_ids") or [])
            if str(value).strip()
        ]
    else:
        expected_faq_ids = [
            str(entry.get("faq_id") or "").strip()
            for entry in list(item.get("expected_faq") or [])
            if str(entry.get("faq_id") or "").strip()
        ]

    if item.get("expected_rule_ids") is not None:
        expected_rule_ids = [
            str(value).strip()
            for value in list(item.get("expected_rule_ids") or [])
            if str(value).strip()
        ]
    else:
        expected_rule_ids = [
            str(entry.get("rule_id") or "").strip()
            for entry in list(item.get("expected_docs") or [])
            if str(entry.get("rule_id") or "").strip()
        ]

    return RetrievalEvalCase(
        case_id=runtime.case_id,
        question=runtime.question,
        expected_faq_ids=expected_faq_ids,
        expected_rule_ids=expected_rule_ids,
        scenario_id=runtime.scenario_id,
        source_filter=runtime.source_filter,
        tenant_id=runtime.tenant_id,
        dataset_id=runtime.dataset_id,
        visibility=runtime.visibility,
        user_role=runtime.user_role,
        kb_version=runtime.kb_version,
    )


def build_config(args: argparse.Namespace) -> RetrievalEvalConfig:
    """从命令行参数构建评估配置对象。"""
    return RetrievalEvalConfig(
        faq_top_k=args.faq_top_k,
        kb_top_k=args.kb_top_k,
        faq_hit_threshold=args.faq_hit_threshold,
        kb_recall_threshold=args.kb_recall_threshold,
        kb_mrr_threshold=args.kb_mrr_threshold,
        scenario_id=args.scenario,
        tenant_id=args.tenant_id,
        dataset_id=args.dataset_id,
        visibility=args.visibility,
        user_role=args.user_role,
        kb_version=args.kb_version,
    )


def build_metric_status(row: dict[str, Any], config: RetrievalEvalConfig) -> list[dict[str, Any]]:
    """生成当前样本所有参与评估指标的阈值状态。

    失败样本排查时，只看到失败指标是不够的；
    这里会把当前样本所有参与计算的指标都列出来，包括：

    - 指标名；
    - 实际值；
    - 阈值；
    - 是否通过；
    - 可读说明。

    如果某个指标为 None，说明这道题不参与该指标计算，不应该判失败。
    """
    checks = [
        ("faq_hit_at_k", config.faq_hit_threshold),
        ("kb_recall_at_k", config.kb_recall_threshold),
        ("kb_rr", config.kb_mrr_threshold),
    ]
    status = []
    for metric_name, threshold in checks:
        value = row.get(metric_name)
        if value is None:
            continue

        passed = value >= threshold
        comparator = "meets" if passed else "below"
        status.append(
            {
                "metric": metric_name,
                "value": value,
                "threshold": threshold,
                "passed": passed,
                "message": f"{metric_name}={value} {comparator} threshold {threshold}",
            }
        )
    return status


def run_retrieval_eval(args: argparse.Namespace) -> dict[str, Any]:
    """执行检索评估并返回完整报告。

    这是当前模块的主入口，最终输出：

    - summary：整体指标汇总；
    - rows：每条样本的明细分数和命中结果。
    """
    service = get_qa_service()
    config = build_config(args)
    items = load_eval_items(args.dataset, args.limit)

    cases: list[RetrievalEvalCase] = []
    traces = []
    rows = []

    for index, item in enumerate(items, start=1):
        case = build_eval_case(item, index, args)
        cases.append(case)

        try:
            # 这里必须走生产检索调试接口，而不是本地拼装假数据，
            # 否则评估结果不能真实反映线上链路表现。
            payload = service.debug_retrieval(
                case.question,
                case.source_filter,
                f"retrieval-eval-{index}",
                kb_version=case.kb_version,
                scenario_id=case.scenario_id,
                tenant_id=case.tenant_id,
                dataset_id=case.dataset_id,
                visibility=case.visibility,
                user_role=case.user_role,
            )
        except Exception as exc:
            payload = {"error": str(exc)}

        trace = build_retrieval_trace(case.case_id, case.question, payload)
        traces.append(trace)
        row = asdict(score_case(case, trace, config))

        metric_status = build_metric_status(row, config)
        metric_errors = [item for item in metric_status if not item["passed"]]
        if row["error"]:
            row["metric_status"] = metric_status
            row["metric_errors"] = metric_errors
        else:
            row["metric_status"] = metric_status
            row["metric_errors"] = metric_errors
            row["error"] = "; ".join(item["message"] for item in metric_errors)

        rows.append(row)

    summary = aggregate_scores_with_ragas(cases, traces, config)
    error_cases = [
        {
            "case_id": row["case_id"],
            "question": row["question"],
            "error": row["error"],
            "metric_status": row.get("metric_status", []),
            "metric_errors": row.get("metric_errors", []),
        }
        for row in rows
        if row["error"]
    ]
    summary["total"] = len(rows)
    summary["errors"] = len(error_cases)
    summary["error_cases"] = error_cases

    return {
        "report_type": "retrieval_ragas_evaluation",
        "dataset": args.dataset,
        "config": {
            "faq_top_k": config.faq_top_k,
            "kb_top_k": config.kb_top_k,
            "faq_hit_threshold": config.faq_hit_threshold,
            "kb_recall_threshold": config.kb_recall_threshold,
            "kb_mrr_threshold": config.kb_mrr_threshold,
            "scenario_id": config.scenario_id,
            "tenant_id": config.tenant_id,
            "dataset_id": config.dataset_id,
            "visibility": config.visibility,
            "user_role": config.user_role,
            "kb_version": config.kb_version,
        },
        "summary": summary,
        "rows": rows,
    }
