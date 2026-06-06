"""Optional model assistance through Hugging Face Inference Providers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from schemas import AnalysisResult


PRIMARY_MODEL_ID = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16"
QUICK_MODEL_ID = "Qwen/Qwen3.5-9B"

MODEL_CHOICES = {
    "deterministic": {
        "label": "Deterministic field notes",
        "model_id": None,
    },
    "nemotron": {
        "label": "NVIDIA Nemotron 3 Nano 30B-A3B assist",
        "model_id": PRIMARY_MODEL_ID,
    },
    "qwen": {
        "label": "Quick small-model assist: Qwen3.5 9B",
        "model_id": QUICK_MODEL_ID,
    },
}


class ChatClient(Protocol):
    def chat_completion(self, *args: Any, **kwargs: Any) -> Any:
        ...


@dataclass(slots=True)
class ModelAssistResult:
    model_id: str
    memo: dict[str, Any]
    note: str


def model_id_for_engine(engine: str) -> str | None:
    choice = MODEL_CHOICES.get(engine)
    if not choice:
        return None
    model_id = choice["model_id"]
    return str(model_id) if model_id else None


def run_model_assist(
    *,
    engine: str,
    result: AnalysisResult,
    narrative_text: str,
    token: str | None = None,
    client: ChatClient | None = None,
) -> ModelAssistResult:
    """Ask the selected model for a concise memo grounded in visible text."""

    model_id = model_id_for_engine(engine)
    if not model_id:
        raise ValueError(f"No model is configured for analysis engine {engine!r}.")

    prompt = build_model_prompt(result, narrative_text)
    if client is None:
        from huggingface_hub import InferenceClient, get_token

        resolved_token = token or os.getenv("HF_TOKEN") or get_token()
        if not resolved_token:
            raise ValueError(
                "Sign in with Hugging Face to enable model assist through "
                "the inference-api OAuth scope."
            )

        inference_client = InferenceClient(
            model=model_id,
            provider=os.getenv("TRACE_FIELD_NOTES_INFERENCE_PROVIDER") or None,
            token=resolved_token,
            timeout=float(os.getenv("TRACE_FIELD_NOTES_MODEL_TIMEOUT", "45")),
        )
    else:
        inference_client = client
    response = inference_client.chat_completion(
        messages=[
            {
                "role": "system",
                "content": (
                    "You analyze visible coding-agent narrative messages. "
                    "Do not infer hidden reasoning. Return JSON only."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        model=model_id,
        max_tokens=900,
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    content = extract_chat_content(response)
    memo = parse_model_json(content)
    return ModelAssistResult(
        model_id=model_id,
        memo=memo,
        note=f"Model assist completed with {model_id}.",
    )


def build_model_prompt(result: AnalysisResult, narrative_text: str) -> str:
    deterministic_json = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
    narrative_excerpt = narrative_text[:12000]
    return f"""Use the deterministic codebook analysis and redacted visible narrative below.

Return JSON with exactly these keys:
- executive_memo: 4-6 sentences for a developer
- detour_memo: 2-4 sentences about productive detours vs wandering
- outcome_audit_memo: 2-4 sentences about completion claims and caveats
- caveats: array of short strings

Rules:
- Analyze only visible narrative messages.
- Do not claim to know hidden reasoning.
- Cite episode IDs where useful.
- Do not include raw secrets, tool outputs, or long quotes.

Deterministic analysis:
{deterministic_json}

Redacted narrative excerpt:
{narrative_excerpt}
"""


def extract_chat_content(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise ValueError("Model response did not contain chat completion content.") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Model response content was empty.")
    return content


def parse_model_json(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("Model response was not valid JSON.") from exc

    required = {
        "executive_memo": str,
        "detour_memo": str,
        "outcome_audit_memo": str,
        "caveats": list,
    }
    for key, expected_type in required.items():
        if key not in parsed or not isinstance(parsed[key], expected_type):
            raise ValueError(f"Model response missing {key!r} as {expected_type.__name__}.")
    parsed["caveats"] = [str(item) for item in parsed["caveats"][:6]]
    return parsed
