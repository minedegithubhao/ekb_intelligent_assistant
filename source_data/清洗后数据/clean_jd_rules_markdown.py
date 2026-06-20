#!/usr/bin/env python3
"""Clean exported JD rule Markdown files without chunking.

Input:
  D:/ai大模型/rag项目实战/原始数据/{企业,个体}

Output:
  D:/ai大模型/rag项目实战/清洗后数据/{企业,个体}
  D:/ai大模型/rag项目实战/清洗后数据/clean_report.csv
"""

from __future__ import annotations

import argparse
import csv
import html
import re
from pathlib import Path


DEFAULT_INPUT_ROOT = Path("D:/ai\u5927\u6a21\u578b/rag\u9879\u76ee\u5b9e\u6218/\u539f\u59cb\u6570\u636e")
DEFAULT_OUTPUT_ROOT = Path("D:/ai\u5927\u6a21\u578b/rag\u9879\u76ee\u5b9e\u6218/\u6e05\u6d17\u540e\u6570\u636e")
CATEGORIES = ["\u4f01\u4e1a", "\u4e2a\u4f53"]


TOC_LINK_RE = re.compile(r"^\s*\[([^\]]{1,80})\]\(https?://[^)]*#.*\)\s*$")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
LOCAL_ANCHOR_LINK_RE = re.compile(r"\[([^\]]+)\]\(#[^)]+\)")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
RULE_META_RE = re.compile(r"^-\s+(rule_id|source_url|label_names|active_time|update_time):\s*(.*)$")


def normalize_heading(line: str) -> str:
    stripped = line.strip()
    stripped = re.sub(r"^\[\]\s*", "", stripped)

    # Convert bold-only headings to a stable heading-ish line.
    bold_match = re.fullmatch(r"\*{2}\s*(.+?)\s*\*{2}", stripped)
    if bold_match:
        inner = bold_match.group(1).strip()
        if re.search(r"第[一二三四五六七八九十百零〇\d]+[章节条]|附则|概述|定义", inner):
            return f"## {inner}"
        return inner

    # Normalize mixed heading + bold, e.g. "# **第一章 概述**".
    stripped = re.sub(r"^(#{1,6})\s*\*{2}\s*(.+?)\s*\*{2}\s*$", r"\1 \2", stripped)
    stripped = re.sub(r"^(#{1,6})([^#\s])", r"\1 \2", stripped)
    return stripped


def clean_markdown_link(match: re.Match[str]) -> str:
    text = match.group(1).strip()
    url = match.group(2).strip()
    if "#" in url and ("rule.jd.com" in url or "learn-jdm.jd.com" in url):
        return text
    return f"{text}（{url}）"


def clean_image(match: re.Match[str]) -> str:
    image_src = match.group(2).strip()
    if image_src.startswith("data:image/"):
        return "图片：内嵌图片已省略"
    return f"图片：{image_src}"


def clean_line(line: str) -> str | None:
    line = html.unescape(line).replace("\u00a0", " ")
    line = line.replace("\ufeff", "")
    line = re.sub(r"\s+", " ", line).strip()

    if not line:
        return ""
    if TOC_LINK_RE.match(line):
        return None
    if re.fullmatch(r"\|+", line):
        return None

    line = IMAGE_RE.sub(clean_image, line)
    line = LOCAL_ANCHOR_LINK_RE.sub(lambda m: m.group(1).strip(), line)
    line = MARKDOWN_LINK_RE.sub(clean_markdown_link, line)
    line = line.replace("[]", "")
    line = re.sub(r"\*\*([^*]+?)\s+\*\*", r"**\1**", line)
    line = re.sub(r"\s+([，。；：！？、）】》])", r"\1", line)
    line = re.sub(r"([（【《])\s+", r"\1", line)
    line = normalize_heading(line)
    return line


def collapse_blank_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    blank = False
    for line in lines:
        if line == "":
            if not blank and result:
                result.append("")
            blank = True
            continue
        result.append(line)
        blank = False
    while result and result[-1] == "":
        result.pop()
    return result


def clean_document(text: str) -> tuple[str, dict[str, int]]:
    original_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned: list[str] = []
    removed_toc_links = 0
    removed_pipe_lines = 0

    for raw_line in original_lines:
        if TOC_LINK_RE.match(raw_line.strip()):
            removed_toc_links += 1
        if re.fullmatch(r"\s*\|+\s*", raw_line):
            removed_pipe_lines += 1

        line = clean_line(raw_line)
        if line is None:
            continue
        cleaned.append(line)

    cleaned = collapse_blank_lines(cleaned)

    # Ensure the first title remains a single H1.
    if cleaned and cleaned[0].startswith("# "):
        cleaned[0] = "# " + cleaned[0][2:].strip()

    output = "\n".join(cleaned).strip() + "\n"
    stats = {
        "original_chars": len(text),
        "cleaned_chars": len(output),
        "original_lines": len(original_lines),
        "cleaned_lines": len(cleaned),
        "removed_toc_links": removed_toc_links,
        "removed_pipe_lines": removed_pipe_lines,
    }
    return output, stats


def read_title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def copy_index_files(input_root: Path, output_root: Path) -> None:
    for name in ["index.csv"]:
        src = input_root / name
        if src.exists():
            (output_root / name).write_bytes(src.read_bytes())
    for category in CATEGORIES:
        src = input_root / category / "index.csv"
        if src.exists():
            target_dir = output_root / category
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "index.csv").write_bytes(src.read_bytes())


def run_clean(input_root: Path, output_root: Path) -> list[dict[str, str | int]]:
    output_root.mkdir(parents=True, exist_ok=True)
    report: list[dict[str, str | int]] = []

    for category in CATEGORIES:
        input_dir = input_root / category
        output_dir = output_root / category
        output_dir.mkdir(parents=True, exist_ok=True)

        for source_path in sorted(input_dir.glob("*.md")):
            text = source_path.read_text(encoding="utf-8")
            cleaned, stats = clean_document(text)
            target_path = output_dir / source_path.name
            target_path.write_text(cleaned, encoding="utf-8")
            report.append(
                {
                    "category": category,
                    "file": source_path.name,
                    "title": read_title(cleaned),
                    **stats,
                }
            )

    copy_index_files(input_root, output_root)
    return report


def write_report(output_root: Path, report: list[dict[str, str | int]]) -> None:
    report_path = output_root / "clean_report.csv"
    fields = [
        "category",
        "file",
        "title",
        "original_chars",
        "cleaned_chars",
        "original_lines",
        "cleaned_lines",
        "removed_toc_links",
        "removed_pipe_lines",
    ]
    with report_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean JD rule Markdown files without chunking.")
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_clean(args.input_root, args.output_root)
    write_report(args.output_root, report)

    counts = {category: 0 for category in CATEGORIES}
    for row in report:
        counts[str(row["category"])] += 1
    print(f"cleaned total={len(report)} output={args.output_root}")
    for category in CATEGORIES:
        print(f"{category}={counts[category]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
