---
title: Trace Field Notes
colorFrom: green
colorTo: gray
sdk: gradio
sdk_version: 5.50.0
app_file: app.py
pinned: false
license: mit
hf_oauth: true
hf_oauth_scopes:
  - inference-api
hf_oauth_expiration_minutes: 480
---

# Trace Field Notes

Trace Field Notes turns coding-agent session logs into qualitative field reports.

Upload a Codex, Claude Code, or Pi Agent JSONL trace. The app ignores raw tool
telemetry by default and analyzes only the agent's visible narrative messages:
what it planned, where it got stuck, how it detoured, how it recovered, and how
it claimed completion.

Built for the Build Small Hackathon as a Gradio app. The default engine uses a
verified deterministic codebook analyzer so the Space can always start and
produce a report. The app also exposes explicit small-model assist modes for
`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` and `Qwen/Qwen3.5-9B` through
Hugging Face Inference Providers when the user signs in with Hugging Face OAuth.

## Run Locally

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Test

```bash
python3.11 -m unittest discover -s tests
```

## Analysis Engines

- `Deterministic field notes`: default, local, no model dependency.
- `Small-model assist: NVIDIA Nemotron 3 Nano 30B-A3B`: uses the hackathon-sized
  30B total-parameter Nemotron model through the signed-in user's
  `inference-api` OAuth scope.
- `Quick small-model assist: Qwen3.5 9B`: optional lower-latency model-assisted
  memo.

If a selected model is unavailable or the user is not signed in, the report
records the reason in model notes and returns the deterministic analysis instead
of failing the whole Space.

## Agent Session Locations

```bash
# Codex
ls ~/.codex/sessions

# Claude Code
ls ~/.claude/projects

# Pi Agent
ls ~/.pi/agent/sessions
```

## Privacy

Agent traces can contain prompts, tool inputs, command outputs, local file paths,
screenshots, secrets, private source code, and personal data. Review and redact
before uploading or sharing publicly. The app defaults to basic regex redaction
and exports only a redacted narrative text file.
