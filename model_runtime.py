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
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

from profiling import get_logger
from schemas import (
    APPRAISALS,
    DETOUR_TYPES,
    DIFFICULTY_TYPES,
    OUTCOME_CLAIMS,
    RECOVERY_PATTERNS,
    RESOLUTION_MODES,
)

logger = get_logger()


PRIMARY_MODEL_ID = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16"
QUICK_MODEL_ID = "openbmb/MiniCPM5-1B"
MODEL_MAX_NEW_TOKENS = 8192

MODEL_CHOICES = {
    "minicpm": {
        "label": "MiniCPM5 1B — quick analysis",
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
class ModelAnalysisResult:
    model_id: str
    analysis: dict[str, Any]
    note: str


def model_id_for_engine(engine: str) -> str | None:
    choice = MODEL_CHOICES.get(engine)
    if not choice:
        return None
    model_id = choice["model_id"]
    return str(model_id) if model_id else None


def resolve_device(device: str | None = None) -> str:
    """Pick the compute device: explicit override, else cuda -> mps -> cpu."""

    if device:
        return device
    import torch

    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def run_model_analysis(
    *,
    engine: str,
    numbered_narrative: str,
    agent_type: str = "unknown",
    codebook_hint: str = "",
    generate: GenerateFn | None = None,
    device: str | None = None,
) -> ModelAnalysisResult:
    """Run the selected model as the primary analyst and return a field report.

    The model identifies and classifies the difficulty episodes and writes the
    session verdict directly from the visible narrative; the deterministic codebook
    is only a fallback (used by the caller if this raises). ``device`` forces the
    compute device for the default local generator; an injected ``generate`` is
    used as-is.
    """

    model_id = model_id_for_engine(engine)
    if not model_id:
        raise ValueError(f"No model is configured for analysis engine {engine!r}.")

    prompt = build_analysis_prompt(
        numbered_narrative, agent_type=agent_type, codebook_hint=codebook_hint
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert analyst of coding-agent session traces. "
                "Judge only the visible narrative; never invent hidden reasoning. "
                "Return one JSON object and nothing else."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    started = time.perf_counter()
    if generate is not None:
        content = generate(messages, model_id=model_id, max_new_tokens=MODEL_MAX_NEW_TOKENS)
        device_label = "injected"
    else:
        device_label = resolve_device(device)
        content = _local_generator(
            messages,
            model_id=model_id,
            max_new_tokens=MODEL_MAX_NEW_TOKENS,
            device=device_label,
        )
    logger.info(
        "model analysis: %s on %s in %.2fs (%d chars in)",
        model_id,
        device_label,
        time.perf_counter() - started,
        len(numbered_narrative),
    )
    analysis = parse_analysis_json(content)
    return ModelAnalysisResult(
        model_id=model_id,
        analysis=analysis,
        note=f"Analysis produced by {model_id}.",
    )


def _local_generator(
    messages: list[dict[str, str]],
    *,
    model_id: str,
    max_new_tokens: int,
    device: str | None = None,
) -> str:
    """Generate text with a locally loaded model on the chosen device.

    Imported lazily: ``torch`` only needs to exist on the GPU Space (or a local
    machine running the model), never for the deterministic path, tests, or
    light local development.
    """

    import torch

    tokenizer, model = _load_model(model_id, device=device)
    chat_inputs = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        return_tensors="pt",
        **_chat_template_kwargs(model_id),
    )
    generation_inputs, prompt_token_count = _prepare_generation_inputs(
        chat_inputs,
        device=model.device,
    )
    with torch.no_grad():
        generated = model.generate(
            **generation_inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )
    completion = generated[0][prompt_token_count:]
    return tokenizer.decode(completion, skip_special_tokens=True)


def _prepare_generation_inputs(chat_inputs: Any, *, device: Any) -> tuple[dict[str, Any], int]:
    """Move tokenizer output to device and return kwargs plus prompt length.

    ``apply_chat_template`` may return either a tensor-like object or a
    ``BatchEncoding``/mapping depending on the tokenizer. ``generate`` accepts
    tensor input through the ``inputs=`` keyword and mapping input through
    expanded kwargs such as ``input_ids`` and ``attention_mask``.
    """

    moved = _move_to_device(chat_inputs, device)
    if isinstance(moved, Mapping):
        generation_inputs = {
            key: _move_to_device(value, device)
            for key, value in moved.items()
        }
        input_ids = generation_inputs.get("input_ids")
        if input_ids is None or not hasattr(input_ids, "shape"):
            raise ValueError("Tokenizer output did not include tensor-shaped input_ids.")
        return generation_inputs, int(input_ids.shape[-1])

    if not hasattr(moved, "shape"):
        raise ValueError("Tokenizer output was neither a tensor nor a mapping.")
    return {"inputs": moved}, int(moved.shape[-1])


def _move_to_device(value: Any, device: Any) -> Any:
    if hasattr(value, "to"):
        return value.to(device)
    return value


def _chat_template_kwargs(model_id: str) -> dict[str, Any]:
    """Model-specific chat-template controls."""

    if model_id.startswith("openbmb/"):
        # MiniCPM5 supports hybrid reasoning; the quick engine keeps thinking
        # off for fast, reliably parseable JSON memos.
        return {"enable_thinking": False}
    return {}


def _load_model(model_id: str, device: str | None = None) -> Any:
    """Lazily load and cache a (tokenizer, model) pair on the chosen device.

    The cache keeps weights resident across requests so only the first call per
    (model, device) pays the load cost. ZeroGPU exposes CUDA inside the
    ``@spaces.GPU`` context; CPU/MPS support lets the app run off-Space (e.g. for
    users without GPU quota, or local development).
    """

    import torch

    resolved = resolve_device(device)
    cache_key = f"{model_id}@{resolved}"
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    from transformers import AutoModelForCausalLM, AutoTokenizer

    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    if resolved == "cuda":
        # The ZeroGPU Space path: load straight onto the GPU in bfloat16.
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            dtype=torch.bfloat16,
            device_map="cuda",
            trust_remote_code=True,
        )
    else:
        # CPU / Apple MPS: fp16 on MPS, fp32 on CPU for numerical stability.
        dtype = torch.float16 if resolved == "mps" else torch.float32
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            dtype=dtype,
            trust_remote_code=True,
        ).to(resolved)
    model.eval()
    logger.info("loaded %s on %s in %.1fs", model_id, resolved, time.perf_counter() - started)
    _MODEL_CACHE[cache_key] = (tokenizer, model)
    return tokenizer, model


def _vocab_block(name: str, vocab: dict[str, str]) -> str:
    return f"{name}:\n" + "\n".join(f"- {key}: {meaning}" for key, meaning in vocab.items())


def build_analysis_prompt(
    numbered_narrative: str, *, agent_type: str = "unknown", codebook_hint: str = ""
) -> str:
    narrative = numbered_narrative[:16000]
    vocab = "\n\n".join(
        [
            _vocab_block("difficulty_type", DIFFICULTY_TYPES),
            _vocab_block("appraisal", APPRAISALS),
            _vocab_block("detour_type", DETOUR_TYPES),
            _vocab_block("resolution_mode", RESOLUTION_MODES),
            _vocab_block("recovery_pattern", RECOVERY_PATTERNS),
            _vocab_block("outcome_claim", OUTCOME_CLAIMS),
        ]
    )
    return f"""Read the agent's visible narrative and produce a structured field report as JSON.

Identify the real DIFFICULTY EPISODES — moments where the agent hit a snag, reassessed,
detoured, recovered, or claimed completion. Ignore instructions, skill files, prompts,
or boilerplate the agent merely read or quoted; those are NOT difficulties. Merge
duplicates. Prefer 1-8 substantive episodes; if there is genuinely no difficulty,
return an empty episodes list.

Return ONE JSON object (first character {{ and last character }}), no prose, EXACTLY:
{{
  "verdict": {{
    "tone": one of ["stable","iterative","detour","partial","risk","unknown"],
    "headline": "<= 12 words, plain language",
    "detail": "2-4 sentences a developer can act on",
    "honesty": one of ["candid","mixed","overclaimed"]
  }},
  "overall_patterns": {{
    "difficulty_style": "1 sentence", "detour_style": "1 sentence",
    "recovery_style": "1 sentence", "risk_or_caveat": "1 sentence"
  }},
  "episodes": [
    {{
      "start_index": <a message index shown below>,
      "end_index": <a message index shown below>,
      "title": "<= 10 words",
      "initial_intention": "1 sentence", "reported_difficulty": "1-2 sentences",
      "difficulty_type": "<one key below>", "appraisal": "<one key below>",
      "strategy_before": "1 sentence", "strategy_after": "1 sentence",
      "detour_type": "<one key below>", "resolution_mode": "<one key below>",
      "recovery_pattern": "<one key below>", "outcome_claim": "<one key below>",
      "productive_detour": one of ["yes","no","mixed","unknown"],
      "evidence_quotes": ["short verbatim quote", "up to 3"],
      "analyst_memo": "1-3 sentences of real insight, NOT a restatement of the codes"
    }}
  ]
}}

Controlled vocabulary (use these keys exactly):
{vocab}

Guidance:
- Every field must contain real content drawn from the trace. NEVER output a
  placeholder such as "<= 10 words", "1 sentence", or "<one key below>" literally.
- difficulty_type, appraisal, detour_type, resolution_mode, recovery_pattern, and
  outcome_claim must each be EXACTLY one key from the vocabulary above (lowercase,
  with underscores). If unsure, use "unknown".
- Be accurate, not generous. If the agent ended unresolved or overclaimed, say so in tone/honesty.
- honesty = "overclaimed" when a success claim outruns the visible evidence.
- start_index / end_index must be message indices that appear below.
- Quote the agent's own words; keep the original language of the quote.
- Do not include secrets or long tool dumps.

Agent type: {agent_type}
Rule-based pre-scan candidate spans (hints only — keep, drop, merge, or add freely): {codebook_hint or "(none)"}

Numbered visible messages:
{narrative}
"""


def parse_analysis_json(content: str) -> dict[str, Any]:
    """Validate the structural shape of the model's field report (codes coerced later)."""

    parsed = _loads_lenient(content)
    episodes = parsed.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("Model response did not include an 'episodes' list.")
    parsed["episodes"] = [episode for episode in episodes if isinstance(episode, dict)]
    if not isinstance(parsed.get("overall_patterns"), dict):
        parsed["overall_patterns"] = {}
    if not isinstance(parsed.get("verdict"), dict):
        parsed["verdict"] = {}
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
        candidates = list(_json_object_candidates(text))
        if not candidates:
            raise ValueError("Model response was not valid JSON.")
        parsed = candidates[-1]

    if not isinstance(parsed, dict):
        raise ValueError("Model response was not a JSON object.")
    return parsed


def _json_object_candidates(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    cursor = 0
    while True:
        start = text.find("{", cursor)
        if start == -1:
            return candidates
        try:
            parsed, consumed = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)
        cursor = start + max(consumed, 1)
