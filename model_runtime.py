"""Local small-model assistance for Trace Field Notes on Hugging Face ZeroGPU.

The analysis models run on the Space GPU through ``transformers``. Heavy imports
(``torch``, ``transformers``) are loaded lazily inside the generator so that the
deterministic analyzer, the test suite, and local development keep working
without GPU dependencies installed. If a model cannot be loaded or its output is
not valid JSON, :func:`analyzer.analyze_trace_file` falls back to the
deterministic codebook and records the reason in the model notes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from schemas import AnalysisResult


PRIMARY_MODEL_ID = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16"
QUICK_MODEL_ID = "Qwen/Qwen3.5-9B"

MODEL_CHOICES = {
    "qwen": {
        "label": "Qwen3.5 9B — quick analysis",
        "model_id": QUICK_MODEL_ID,
    },
    "nemotron": {
        "label": "NVIDIA Nemotron 3 Nano 30B-A3B — deeper analysis",
        "model_id": PRIMARY_MODEL_ID,
    },
    "deterministic": {
        "label": "Rule-based — instant, no model",
        "model_id": None,
    },
}

# (messages, *, model_id, max_new_tokens) -> raw model text.
GenerateFn = Callable[..., str]

_MODEL_CACHE: dict[str, Any] = {}


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
    generate: GenerateFn | None = None,
) -> ModelAssistResult:
    """Run the selected model on the GPU and return a concise grounded memo."""

    model_id = model_id_for_engine(engine)
    if not model_id:
        raise ValueError(f"No model is configured for analysis engine {engine!r}.")

    prompt = build_model_prompt(result, narrative_text)
    messages = [
        {
            "role": "system",
            "content": (
                "You analyze visible coding-agent narrative messages. "
                "Do not infer hidden reasoning. Return JSON only."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    generator = generate or _local_generator
    content = generator(messages, model_id=model_id, max_new_tokens=900)
    memo = parse_model_json(content)
    return ModelAssistResult(
        model_id=model_id,
        memo=memo,
        note=f"Model assist completed on the Space GPU with {model_id}.",
    )


def _local_generator(
    messages: list[dict[str, str]],
    *,
    model_id: str,
    max_new_tokens: int,
) -> str:
    """Generate text with a locally loaded model on the ZeroGPU device.

    Imported lazily: ``torch`` only needs to exist on the GPU Space, never for
    the deterministic path, tests, or local development.
    """

    import torch

    tokenizer, model = _load_model(model_id)
    inputs = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        return_tensors="pt",
    ).to(model.device)
    with torch.no_grad():
        generated = model.generate(
            inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )
    completion = generated[0][inputs.shape[-1]:]
    return tokenizer.decode(completion, skip_special_tokens=True)


def _load_model(model_id: str) -> Any:
    """Lazily load and cache a (tokenizer, model) pair on the GPU.

    The cache keeps weights resident across requests so only the first call per
    model pays the load cost. ZeroGPU exposes CUDA inside the ``@spaces.GPU``
    context, which is where this runs.
    """

    cached = _MODEL_CACHE.get(model_id)
    if cached is not None:
        return cached

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        torch_dtype=torch.bfloat16,
        device_map="cuda",
        trust_remote_code=True,
    )
    model.eval()
    _MODEL_CACHE[model_id] = (tokenizer, model)
    return tokenizer, model


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


def parse_model_json(content: str) -> dict[str, Any]:
    parsed = _loads_lenient(content)

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


def _loads_lenient(content: str) -> dict[str, Any]:
    """Parse JSON from a model that may wrap it in prose or code fences."""

    if not isinstance(content, str) or not content.strip():
        raise ValueError("Model response content was empty.")

    text = content.strip()
    fence = re.match(r"^```[a-zA-Z0-9]*\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed: Any = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Model response was not valid JSON.")
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("Model response was not valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Model response was not a JSON object.")
    return parsed
