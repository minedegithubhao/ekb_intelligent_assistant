"""脚本层公共工具。

当前版本只保留检索评估脚本需要的最小基础设施：

- UTF-8 输出处理
- JSON 写文件

这样可以让评估脚本关注业务流程，而不是重复写文件和编码样板代码。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def configure_utf8_stdio() -> None:
    """把脚本标准输出统一成 UTF-8。

    Windows PowerShell 环境下，如果不主动设成 UTF-8，中文 JSON 很容易乱码。
    这里集中处理一次，避免每个脚本重复写。
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def write_json_file(path: str | Path, payload: dict[str, Any]) -> str:
    """把对象写成 JSON 文件，并返回写入路径。

    输出统一使用：
    - `ensure_ascii=False` 保留中文；
    - `indent=2` 方便人工阅读；
    - 自动创建父目录，便于脚本直接落报告。
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(output_path)
