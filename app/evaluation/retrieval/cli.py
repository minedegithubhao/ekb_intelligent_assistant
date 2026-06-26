"""基于 Ragas 的检索评估脚本。

当前脚本只评估三个指标：

- FAQ Hit Rate@K
- 知识库 Recall@K
- 知识库 MRR

它的设计目标不是做通用评测平台，而是作为工程回归工具：

- 每次调整 FAQ 召回策略后，快速看 FAQ TopK 命中率是否退化；
- 每次调整 KB 检索、切分或索引后，快速看 Recall/MRR 是否退化；
- 能把整体指标和单题明细一起写出来，方便排查。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.evaluation.common.file_utils import configure_utf8_stdio, write_json_file
from app.evaluation.retrieval.runner import run_retrieval_eval


EVALUATION_REPORT_DIR = Path("reports") / "evaluation"


def default_output_path(dataset: str) -> Path:
    """构建默认报告输出路径。

    命名规则里带上：
    - UTC 时间戳：方便版本比较；
    - 数据集名：方便快速识别当前报告对应哪个评估集。
    """
    EVALUATION_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = Path(dataset).stem or "retrieval_eval"
    return EVALUATION_REPORT_DIR / f"{stamp}_{name}_ragas.json"


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。

    参数设计尽量和参考项目的评测脚本保持一致，这样你后续切换或合并脚本时更自然。
    """
    parser = argparse.ArgumentParser(description="Evaluate retrieval metrics with Ragas.")
    parser.add_argument(
        "--dataset",
        default=str(Path("resources") / "evaluation" / "datasets" / "mock_retrieval_eval.json"),
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", default="")
    parser.add_argument("--faq-top-k", type=int, default=5)
    parser.add_argument("--kb-top-k", type=int, default=10)
    parser.add_argument("--faq-hit-threshold", type=float, default=1.0)
    parser.add_argument("--kb-recall-threshold", type=float, default=1.0)
    parser.add_argument("--kb-mrr-threshold", type=float, default=1.0)
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--dataset-id", default=None)
    parser.add_argument("--visibility", default=None)
    parser.add_argument("--user-role", default=None)
    parser.add_argument("--kb-version", default=None)
    return parser


def main() -> None:
    """执行检索评估并输出 JSON 报告。"""
    configure_utf8_stdio()
    parser = build_arg_parser()
    args = parser.parse_args()

    report = run_retrieval_eval(args)
    output_path = Path(args.output) if args.output else default_output_path(args.dataset)
    write_json_file(output_path, report)

    # 控制台直接打印 JSON，方便本地调试和 CI/脚本链路读取。
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
