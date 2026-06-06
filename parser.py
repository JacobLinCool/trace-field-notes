"""Trace parsing and narrative-message extraction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from schemas import AgentType, NarrativeMessage


TEXT_KEYS = ("text", "message", "summary", "transcript", "output", "body")
TOOLISH_TYPE_FRAGMENTS = (
    "tool",
    "function_call",
    "function_result",
    "command",
    "exec",
    "screenshot",
    "image",
    "patch",
    "diff",
)
TOOLISH_KEYS = (
    "tool_call_id",
    "tool_use_id",
    "tool_calls",
    "tool_results",
    "function_call",
    "arguments",
    "input_json",
    "output_json",
)


class TraceParseError(ValueError):
    """Raised when an uploaded trace cannot be parsed into narrative messages."""


def parse_trace(
    path: str | Path,
    *,
    include_user_context: bool = True,
    ignore_tool_calls: bool = True,
) -> tuple[list[NarrativeMessage], AgentType]:
    """Parse an uploaded trace and return visible narrative messages plus agent guess."""

    trace_path = Path(path)
    records = load_records(trace_path)
    agent_type = guess_agent_type(records, trace_path)

    messages: list[NarrativeMessage] = []
    for raw_index, record in enumerate(records):
        for role, text, timestamp, source in normalize_record(
            record,
            raw_index=raw_index,
            ignore_tool_calls=ignore_tool_calls,
        ):
            cleaned = normalize_whitespace(text)
            if not cleaned:
                continue
            if role == "assistant" or (role == "user" and include_user_context):
                messages.append(
                    NarrativeMessage(
                        index=len(messages),
                        role=role,
                        text=cleaned,
                        timestamp=timestamp,
                        source=source,
                    )
                )

    return messages, agent_type


def load_records(path: Path) -> list[Any]:
    """Load JSONL, JSON, or plain text records from disk."""

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise TraceParseError(f"Could not read uploaded file: {exc}") from exc

    if not text.strip():
        raise TraceParseError("The uploaded trace is empty.")

    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise TraceParseError(f"Invalid JSON: {exc}") from exc
        return records_from_json(parsed)

    if suffix in {".jsonl", ".log", ".txt", ""}:
        records = try_jsonl(text)
        if records:
            return records
        return records_from_plain_text(text)

    records = try_jsonl(text)
    return records if records else records_from_plain_text(text)


def records_from_json(parsed: Any) -> list[Any]:
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("messages", "turns", "events", "records", "items"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
        return [parsed]
    return [{"type": "text", "role": "assistant", "content": str(parsed)}]


def try_jsonl(text: str) -> list[Any]:
    records: list[Any] = []
    saw_json = False
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
            saw_json = True
        except json.JSONDecodeError:
            if saw_json:
                records.append({"type": "text", "role": "assistant", "content": line})
            else:
                return []
    return records if saw_json else []


def records_from_plain_text(text: str) -> list[Any]:
    records: list[Any] = []
    current_role = "assistant"
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        content = "\n".join(buffer).strip()
        if content:
            records.append({"type": "text", "role": current_role, "content": content})
        buffer = []

    for line in text.splitlines():
        lowered = line.strip().lower()
        if lowered.startswith(("assistant:", "agent:")):
            flush()
            current_role = "assistant"
            buffer.append(line.split(":", 1)[1].strip())
        elif lowered.startswith("user:"):
            flush()
            current_role = "user"
            buffer.append(line.split(":", 1)[1].strip())
        else:
            buffer.append(line)
    flush()

    if not records:
        records.append({"type": "text", "role": "assistant", "content": text})
    return records


def guess_agent_type(records: Iterable[Any], path: Path | None = None) -> AgentType:
    path_text = str(path or "").lower()
    if ".codex" in path_text or "/codex/" in path_text:
        return "codex"
    if ".claude" in path_text or "claude" in path_text:
        return "claude_code"
    if ".pi" in path_text or "/pi/" in path_text:
        return "pi"

    sample = list(records[:20] if isinstance(records, list) else records)
    for record in sample:
        if not isinstance(record, dict):
            continue
        top_type = str(record.get("type", "")).lower()
        payload = record.get("payload")
        message = record.get("message")
        if top_type in {"session_meta", "turn_context", "response_item", "event_msg"}:
            return "codex"
        if isinstance(payload, dict) and (
            payload.get("originator") == "codex_cli"
            or str(payload.get("type", "")).startswith(("agent_", "user_"))
        ):
            return "codex"
        if "parentUuid" in record or "sessionId" in record or "userType" in record:
            return "claude_code"
        if isinstance(message, dict) and "claude" in str(message.get("model", "")).lower():
            return "claude_code"
        if top_type.startswith("pi_") or "pi agent" in json.dumps(record, default=str).lower()[:1000]:
            return "pi"
    return "unknown"


def normalize_record(
    record: Any,
    *,
    raw_index: int,
    ignore_tool_calls: bool,
) -> list[tuple[str, str, str | None, str]]:
    """Return zero or more role/text/timestamp/source tuples from one raw record."""

    if isinstance(record, str):
        return [("assistant", record, None, "plain_text")]
    if not isinstance(record, dict):
        return [("assistant", str(record), None, "plain_text")]

    timestamp = find_timestamp(record)
    candidates: list[tuple[str | None, Any, str]] = []

    payload = record.get("payload")
    if isinstance(payload, dict):
        role = normalize_role(payload.get("role"))
        if role is None and str(payload.get("type", "")).lower().startswith("agent"):
            role = "assistant"
        if role is None and str(payload.get("type", "")).lower().startswith("user"):
            role = "user"
        for key in ("content", "message", "summary", "text"):
            if key in payload:
                candidates.append((role, payload[key], f"payload.{key}"))

    message = record.get("message")
    if isinstance(message, dict):
        role = normalize_role(message.get("role")) or normalize_role(record.get("type"))
        for key in ("content", "text", "message"):
            if key in message:
                candidates.append((role, message[key], f"message.{key}"))
    elif message is not None:
        role = normalize_role(record.get("role")) or normalize_role(record.get("type"))
        candidates.append((role, message, "message"))

    role = normalize_role(record.get("role")) or normalize_role(record.get("type"))
    for key in ("content", "text", "summary", "body"):
        if key in record:
            candidates.append((role, record[key], key))

    normalized: list[tuple[str, str, str | None, str]] = []
    seen: set[tuple[str, str]] = set()
    for maybe_role, content, source in candidates:
        role = maybe_role or "assistant"
        if role not in {"assistant", "user"}:
            continue
        text = extract_text(content, ignore_tool_calls=ignore_tool_calls)
        if not text:
            continue
        key = (role, text)
        if key in seen:
            continue
        seen.add(key)
        normalized.append((role, text, timestamp, source))

    return normalized


def normalize_role(value: Any) -> str | None:
    role = str(value or "").lower()
    if role in {"assistant", "agent", "agent_message", "response_item"}:
        return "assistant"
    if role in {"user", "human", "user_message"}:
        return "user"
    return None


def find_timestamp(record: dict[str, Any]) -> str | None:
    for key in ("timestamp", "created_at", "time", "date"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("payload", "message", "snapshot"):
        value = record.get(key)
        if isinstance(value, dict):
            nested = find_timestamp(value)
            if nested:
                return nested
    return None


def extract_text(content: Any, *, ignore_tool_calls: bool) -> str:
    """Extract visible prose from known chat content shapes."""

    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (int, float, bool)):
        return str(content)
    if isinstance(content, list):
        parts = [extract_text(item, ignore_tool_calls=ignore_tool_calls) for item in content]
        return "\n\n".join(part for part in parts if part.strip())
    if isinstance(content, dict):
        if ignore_tool_calls and is_toolish(content):
            return ""
        for key in TEXT_KEYS:
            value = content.get(key)
            if value is not None:
                text = extract_text(value, ignore_tool_calls=ignore_tool_calls)
                if text.strip():
                    return text
        if "content" in content:
            return extract_text(content["content"], ignore_tool_calls=ignore_tool_calls)
    return ""


def is_toolish(item: dict[str, Any]) -> bool:
    item_type = str(item.get("type", "")).lower()
    role = str(item.get("role", "")).lower()
    name = str(item.get("name", "")).lower()
    if role == "tool":
        return True
    if any(fragment in item_type for fragment in TOOLISH_TYPE_FRAGMENTS):
        return True
    if any(fragment in name for fragment in TOOLISH_TYPE_FRAGMENTS):
        return True
    return any(key in item for key in TOOLISH_KEYS)


def normalize_whitespace(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)
