---
title: Trace Field Notes
colorFrom: green
colorTo: gray
sdk: gradio
sdk_version: 5.50.0
app_file: app.py
pinned: false
license: mit
---

# Trace Field Notes

Trace Field Notes turns coding-agent session logs into qualitative field reports.

Upload a Codex, Claude Code, or Pi Agent JSONL trace. The app ignores raw tool
telemetry by default and analyzes only the agent's visible narrative messages:
what it planned, where it got stuck, how it detoured, how it recovered, and how
it claimed completion.

Built for the Build Small Hackathon as a Gradio app. The stable MVP uses a
verified deterministic codebook analyzer so the Space can always start and
produce a report; the analysis schema is model-ready for small-model assistance.

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
