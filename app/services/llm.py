"""LLM client helpers for query rewriting and answer generation."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.config import LLMConfig, get_runtime_config
from app.core.exceptions import ServiceUnavailableException
from app.schemas.retrieval import RetrievalEvidence
from app.schemas.retrieval_config import RetrievalHotConfigValues


CHAT_COMPLETIONS_SUFFIX = "/chat/completions"


def generate_query_variants(question: str, count: int) -> list[str]:
    """Generate LLM query variants for retrieval."""

    if count <= 0:
        return []
    content = chat_completion(
        [
            {
                "role": "system",
                "content": (
                    "你是RAG检索query改写器。请在不改变用户意图、不扩大问题范围的前提下，"
                    "生成适合向量检索和关键词检索的中文query变体。只返回JSON数组，不要返回解释。"
                ),
            },
            {
                "role": "user",
                "content": f"原问题：{question}\n需要生成数量：{count}\n返回格式：[\"变体1\", \"变体2\"]",
            },
        ],
        temperature=0.4,
        max_tokens=min(1024, max(256, count * 128)),
    )
    return _unique_non_empty(_parse_json_string_array(content))[:count]


def rewrite_follow_up_question(
    question: str,
    history_messages: Sequence[Mapping[str, Any]],
    hot: RetrievalHotConfigValues,
) -> str:
    """Rewrite a short follow-up question into a standalone retrieval question."""

    history_text = _format_history_messages(history_messages, max_chars=hot.history_summary_max_chars)
    if not history_text:
        return question
    content = chat_completion(
        [
            {
                "role": "system",
                "content": (
                    "你负责将用户追问改写成独立、完整、适合检索的问题。"
                    "必须保持原意，不要回答问题。只输出改写后的问题本身。"
                ),
            },
            {
                "role": "user",
                "content": f"历史对话：\n{history_text}\n\n当前追问：{question}",
            },
        ],
        temperature=0.1,
        max_tokens=256,
    )
    cleaned = _strip_code_fence(content).strip()
    return cleaned or question


def generate_answer(question: str, evidence: Sequence[RetrievalEvidence]) -> str:
    """Generate a final answer strictly grounded in retrieved evidence."""

    evidence_text = _format_evidence(evidence)
    if not evidence_text:
        return "知识库中没有找到足够可靠的依据。"
    return chat_completion(
        [
            {
                "role": "system",
                "content": (
                    "你是企业知识库问答助手。只能基于给定证据回答；"
                    "如果证据不足，请明确说明知识库中没有找到足够可靠的依据。"
                    "回答要简洁、准确，不要编造证据中没有的信息。"
                ),
            },
            {
                "role": "user",
                "content": f"用户问题：{question}\n\n证据：\n{evidence_text}",
            },
        ],
        temperature=0.2,
    )


def chat_completion(
    messages: Sequence[Mapping[str, str]],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Call the configured OpenAI-compatible chat-completions endpoint."""

    config = get_runtime_config().app.llm
    api_key = _resolve_api_key(config)
    if not api_key:
        raise ServiceUnavailableException("llm api key is not configured")

    payload: dict[str, Any] = {
        "model": config.model,
        "messages": [{"role": item["role"], "content": item["content"]} for item in messages],
        "temperature": config.temperature if temperature is None else temperature,
        "max_tokens": config.max_tokens if max_tokens is None else max_tokens,
    }
    response = _post_json_with_retries(
        _chat_completions_url(config.base_url),
        payload,
        api_key=api_key,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
    )
    try:
        return str(response["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ServiceUnavailableException("invalid llm response") from exc


def _post_json_with_retries(
    url: str,
    payload: Mapping[str, Any],
    *,
    api_key: str,
    timeout: int,
    max_retries: int,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    for attempt in range(max_retries + 1):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read().decode("utf-8")
            parsed = json.loads(data)
            if not isinstance(parsed, dict):
                raise ServiceUnavailableException("invalid llm response")
            return parsed
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                raise ServiceUnavailableException(f"llm request failed: {exc.code}") from exc
            if attempt >= max_retries:
                raise ServiceUnavailableException(f"llm request failed: {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt >= max_retries:
                raise ServiceUnavailableException("llm request failed") from exc
        time.sleep(0.5 * (attempt + 1))
    raise ServiceUnavailableException("llm request failed")


def _resolve_api_key(config: LLMConfig) -> str | None:
    return _clean_optional(config.api_key) or _clean_optional(os.getenv("KNOWFORGE_LLM_API_KEY")) or _clean_optional(
        os.getenv("DASHSCOPE_API_KEY")
    )


def _chat_completions_url(base_url: str) -> str:
    cleaned = base_url.rstrip("/")
    if cleaned.endswith(CHAT_COMPLETIONS_SUFFIX):
        return cleaned
    return f"{cleaned}{CHAT_COMPLETIONS_SUFFIX}"


def _parse_json_string_array(content: str) -> list[str]:
    cleaned = _strip_code_fence(content).strip()
    candidates = [cleaned]
    match = re.search(r"\[[\s\S]*\]", cleaned)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def _format_history_messages(messages: Sequence[Mapping[str, Any]], *, max_chars: int) -> str:
    lines: list[str] = []
    for item in messages:
        role = str(item.get("role") or "unknown")
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    text = "\n".join(lines)
    return text[-max_chars:] if max_chars > 0 else text


def _format_evidence(evidence: Sequence[RetrievalEvidence]) -> str:
    chunks: list[str] = []
    for index, item in enumerate(evidence, start=1):
        title = item.title or item.source_doc_id or item.evidence_id
        content = item.answer or item.parent_content or item.text
        chunks.append(f"[{index}] 类型：{item.source_type}\n标题：{title}\n内容：{content}")
    return "\n\n".join(chunks)


def _strip_code_fence(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _unique_non_empty(values: Sequence[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        unique.append(cleaned)
        seen.add(cleaned)
    return unique


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
