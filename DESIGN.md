# Agent Trace Narrative Analyzer — Hackathon App Design Doc

版本：v0.2
目標平台：Hugging Face Space / Gradio App
目標 hackathon：Build Small Hackathon 2026
主要使用者：使用 Codex、Claude Code、Pi Agent 等 coding agent 的開發者，想理解「agent 是怎麼卡住、繞路、恢復、收束」的人。

---

## 1. 一句話概念

**Agent Trace Narrative Analyzer** 是一個 Gradio App：使用者上傳 Codex / Claude Code / Pi Agent 的 session log（JSONL），App 不分析 tool-call 細節，而是只讀 agent 自己寫出的 progress / assistant messages，抽出「困難片段」並產生一份可讀的 qualitative report：

- agent 遇到哪些困難？
- 它怎麼理解困難？
- 它有沒有繞路或改變策略？
- 它用了什麼解決方式？
- 它花了多久從困難走到收束？如果 trace 有 timestamp。
- 它最後是有把限制講清楚，還是太快宣稱完成？

這個產品的核心不是 benchmark，也不是 tool-use telemetry，而是 **coding agent 的「敘事性問題解決歷程」分析**。

---

## 2. Hackathon fit

Build Small Hackathon 的精神是「用 ≤32B 的小模型，做小而真實、有趣、可展示的東西」。官方規則包含：

- small models only：模型總參數必須 ≤32B。
- 必須是 Gradio app，並部署成 Hugging Face Space。
- 需要 short demo video 與 social-media post。
- Backyard AI track 重視：問題是否 specific and real、是否真的有人用、是否誠實符合 small-model constraint、Gradio app polish。
- Thousand Token Wood track 重視 delight / originality / AI 是否是 load-bearing。
- Bonus badges 中有一個與 trace 很貼近：**Sharing is Caring / Open trace**，也有 **Field Notes** 可透過 blog/report 加分。

模型敘事建議：使用 `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` 作為主模型。它的 total parameters 是 30B，符合 ≤32B 上限；同時它是 MoE，每 token active parameters 約 3.5B，很適合用來講「small active compute, agentic analysis」的 hackathon 故事。

本 app 建議定位在 **Backyard AI**：服務一群很具體的人，也就是正在用 coding agents 的 builder / hackathon participant / developer。他們真實會遇到的問題是：agent session 很長，最後 patch 對不對不容易說清楚，但更難的是理解「agent 到底怎麼走到這裡」。

可順手爭取的 badges / awards：

- **Best Agent**：如果 app 本身也提供 agent-callable workflow。
- **Sharing is Caring / Open trace**：提供「如何把已 redacted traces 分享到 Hub」的教學或範例。
- **Field Notes**：用 app 產出的 reports 寫一篇短文，展示從 traces 裡看見的 agent behavior patterns。
- **Off-Brand / Custom UI**：如果前端視覺做得像「trail map / field notebook」。

---

## 3. 產品名稱候選

1. **Trace Field Notes**
2. **Agent Detour Map**
3. **Trace Cartographer**
4. **Agent Recovery Lens**
5. **Small Trace, Big Journey**

建議用：**Trace Field Notes**。它符合 hackathon 的 woodland / field-notes 氣質，也強調 qualitative analysis，而不是 leaderboard。

---

## 4. 使用者體驗流程

### 4.1 首頁結構

首頁第一眼應該看到：

**Hero title**

> Trace Field Notes
> See how your coding agent got stuck, detoured, recovered, and claimed success.

**Short explanation**

> Upload a Codex / Claude Code / Pi Agent JSONL session log. This app analyzes the agent's narrated progress messages, not raw tool telemetry, and turns the session into a qualitative map of difficulties, detours, recovery patterns, and outcome claims.

**Privacy warning**

> Agent traces may include prompts, tool inputs, command output, local paths, screenshots, secrets, private code, and personal data. Review and redact before uploading or sharing publicly.

**How to find your session log**

官方 HF Agent Traces docs 目前列出這些本機路徑：

| Agent | Local session directory |
|---|---|
| Claude Code | `~/.claude/projects` |
| Codex | `~/.codex/sessions` |
| Pi Agent | `~/.pi/agent/sessions` |

首頁要提供 copyable instructions：

```bash
# Codex
ls ~/.codex/sessions

# Claude Code
ls ~/.claude/projects

# Pi Agent
ls ~/.pi/agent/sessions
```

**Upload area**

- File input: `.jsonl`, `.json`, `.txt`, `.log`
- Checkbox: `Redact likely secrets before analysis`，預設 on
- Checkbox: `Include user prompts as context`，預設 on
- Checkbox: `Ignore tool call contents`，預設 on and locked for MVP
- Button: `Analyze my trace`

**Agent-callable area**

> Using Codex or Claude Code? Point your agent at this Space's `agents.md`. It can find your local session log, upload it, and call the analysis endpoint for you.

顯示一段 prompt：

```text
Find my latest coding-agent session log, review it for secrets, then use this Space via its agents.md endpoint to upload the JSONL file and request a narrative difficulty analysis. Do not publish the raw trace. Return the report and any caveats.

Space agents.md:
https://huggingface.co/spaces/<namespace>/<space-name>/agents.md
```

---

## 5. Agent-callable workflow via agents.md

Hugging Face / Gradio 會替每個 Gradio Space 提供 plain-text `agents.md` endpoint。coding agents 可以讀取它來取得：

- API schema URL
- call endpoint
- poll endpoint
- file-upload instructions
- auth hint

所以 MVP 不需要另外實作 custom API。只要 Gradio function 的輸入輸出定義清楚，`agents.md` 就會讓 Codex / Claude Code 之類的工具知道如何呼叫。

### 5.1 Gradio function 建議

主要 endpoint：

```python
def analyze_trace(
    trace_file,
    include_user_context: bool = True,
    redact_secrets: bool = True,
    ignore_tool_calls: bool = True,
    report_style: str = "field_notes",
):
    """
    Input: Codex / Claude Code / Pi Agent JSONL session log.
    Output: Markdown report + structured episode JSON + downloadable redacted narrative text.
    """
```

回傳：

```python
return report_markdown, episode_json, redacted_narrative_file
```

### 5.2 在 UI 中提供給 Codex / Claude Code 的 prompt

```text
Use this Space as a tool.
1. Read: https://huggingface.co/spaces/<namespace>/<space-name>/agents.md
2. Find my latest local agent session log:
   - Codex: ~/.codex/sessions
   - Claude Code: ~/.claude/projects
   - Pi Agent: ~/.pi/agent/sessions
3. Review and redact secrets or private code before upload.
4. Upload the JSONL to the Space.
5. Ask for narrative difficulty analysis.
6. Return the report. Do not publish the raw trace.
```

---

## 6. What the app analyzes

本 app 不以 tool calls 為主要分析對象。它只使用：

- assistant / agent narrative messages
- visible progress messages
- planning messages
- self-reported problems
- self-reported strategy shifts
- final summary / outcome claims
- optional user prompts as context

MVP 預設忽略：

- raw tool inputs
- raw tool outputs
- command stdout / stderr
- full file diffs
- private code snippets inside tool outputs

重要措辭：

> We analyze the **agent's narrated process**, not its hidden internal reasoning and not the complete tool telemetry.

這樣比較安全，也比較符合質性分析：我們不是宣稱知道 agent 真正怎麼想，只分析它明確寫出來的問題處理敘事。

---

## 7. 核心分析單位：Difficulty Episode

不要以每個 message 或每個 tool call 為單位。分析單位是：

> 一段 agent 原本想做某件事，遇到阻礙，重新評估，改變或維持策略，嘗試處理，最後收束或未收束的片段。

核心流程：

```text
Initial intention
→ Reported difficulty
→ Appraisal
→ Strategy shift / detour
→ Attempted resolution
→ Outcome claim
```

中文：

```text
原本意圖
→ 遇到的困難
→ 對困難的判斷
→ 策略轉換 / 繞路
→ 解決嘗試
→ 結果宣稱
```

---

## 8. Codebook

### 8.1 Difficulty Type

| Code | 說明 |
|---|---|
| `requirement_uncertainty` | 需求、規格、使用者意圖不清楚 |
| `localization_difficulty` | 不知道問題在哪個模組 / 檔案 / 函式 |
| `architecture_complexity` | 發現系統結構、依賴或 shared component 比預期複雜 |
| `implementation_difficulty` | 知道方向但不確定怎麼實作 |
| `compatibility_risk` | 擔心改 A 會破壞 B，或需要保留既有行為 |
| `verification_difficulty` | 不知道怎麼確認修好了 |
| `environment_blocker` | 測試、依賴、環境、權限等問題 |
| `insufficient_context` | agent 表示需要更多上下文 |
| `conflicting_assumptions` | 原本假設和新資訊衝突 |
| `unknown` | 無法判斷 |

### 8.2 Appraisal

| Code | 說明 |
|---|---|
| `local_fix_possible` | agent 把問題視為可局部修補 |
| `needs_more_context` | agent 認為需要更多資訊 |
| `initial_hypothesis_wrong` | agent 承認原本假設可能錯 |
| `risk_is_higher_than_expected` | agent 意識到副作用或風險較高 |
| `scope_too_large` | agent 認為原方案太大，需縮小 |
| `needs_alternative_path` | agent 開始尋找替代路徑 |
| `cannot_reliably_verify` | agent 承認無法可靠驗證 |
| `task_boundary_unclear` | agent 認為任務邊界不清 |

### 8.3 Strategy Shift / Detour Type

| Code | 說明 |
|---|---|
| `direct_continuation` | 沿用原策略 |
| `decomposition` | 拆解問題 |
| `scope_narrowing` | 縮小修改或分析範圍 |
| `alternative_path` | 換一條路處理 |
| `workaround` | 不解根因，先繞過 |
| `rollback_or_reversal` | 放棄前一方向或撤回 |
| `hypothesis_switch` | 換一個問題假設 |
| `verification_shift` | 改變驗證方式 |
| `ask_or_defer` | 請求使用者資訊或暫停判斷 |
| `premature_closure` | 沒處理完就收束 |

### 8.4 Resolution Mode

| Code | 說明 |
|---|---|
| `information_gathering` | 透過更多上下文解決 |
| `problem_reframing` | 重新定義問題 |
| `minimal_patch` | 做最小修改 |
| `structural_change` | 採用較大結構變更 |
| `defensive_handling` | 加 fallback、guard、error handling |
| `alternative_implementation` | 換一種實作方式 |
| `goal_reduction` | 降低目標或只解部分問題 |
| `explicit_limitation` | 明確承認限制 |
| `narrative_rationalization` | 用流暢敘事合理化，但未見真策略轉換 |

### 8.5 Recovery Pattern

| Code | 說明 |
|---|---|
| `smooth_recovery` | 快速理解困難並恢復推進 |
| `iterative_recovery` | 經過幾次嘗試逐步接近 |
| `detour_recovery` | 繞路後恢復 |
| `partial_recovery` | 解了一部分，保留限制 |
| `failed_recovery` | 嘗試但沒有走出困境 |
| `avoidant_recovery` | 跳過困難，改做旁邊的事 |
| `overconfident_recovery` | 困難未清楚解決但宣稱成功 |
| `reflective_recovery` | 明確說明原假設錯在哪並修正 |

### 8.6 Outcome Claim

| Code | 說明 |
|---|---|
| `resolved_with_confidence` | 明確宣稱已解決 |
| `resolved_with_caveat` | 宣稱解決，但有保留條件 |
| `partially_resolved` | 說明只完成一部分 |
| `not_resolved` | 承認未解決 |
| `needs_verification` | 說還需要測試 / 確認 |
| `uncertain_but_proceeding` | 不確定但繼續 |
| `premature_success_claim` | 證據或敘事不足卻宣稱完成 |

---

## 9. Structured Episode Schema

LLM 或 parser 最終應輸出以下 JSON：

```json
{
  "trace_title": "string",
  "agent_type_guess": "codex | claude_code | pi | unknown",
  "analysis_scope": "assistant narrative messages only",
  "privacy_notes": ["string"],
  "episodes": [
    {
      "episode_id": "E01",
      "title": "string",
      "message_span": {
        "start_index": 0,
        "end_index": 3,
        "start_time": "optional timestamp",
        "end_time": "optional timestamp",
        "duration_label": "e.g. 4m 20s / unknown"
      },
      "initial_intention": "string",
      "reported_difficulty": "string",
      "difficulty_type": "one code from codebook",
      "appraisal": "one code from codebook",
      "strategy_before": "string",
      "strategy_after": "string",
      "detour_type": "one code from codebook",
      "resolution_mode": "one code from codebook",
      "recovery_pattern": "one code from codebook",
      "outcome_claim": "one code from codebook",
      "productive_detour": "yes | no | mixed | unknown",
      "evidence_quotes": [
        "short quote from agent message, <= 30 words"
      ],
      "analyst_memo": "string"
    }
  ],
  "overall_patterns": {
    "difficulty_style": "string",
    "detour_style": "string",
    "recovery_style": "string",
    "risk_or_caveat": "string"
  }
}
```

---

## 10. Report design

分析結果頁面不要像 dashboard metrics，而要像「field report」。建議分成 6 個區塊。

### 10.1 Executive Summary

短短 5–8 句：

- 這個 trace 的主線是什麼？
- agent 主要遇到哪些困難？
- 它的恢復方式偏哪一種？
- 有沒有明顯繞路？
- 最後宣稱是否保守、清楚、有 caveat？

### 10.2 Journey Timeline

用時間線或 cards 顯示每個 difficulty episode：

```text
E01 — Initial misunderstanding
Intention: ...
Difficulty: ...
Shift: ...
Resolution: ...
Outcome claim: ...
Duration: 3m 12s / unknown
```

視覺建議：

- green：smooth / reflective recovery
- yellow：partial / uncertain recovery
- red：failed / overconfident / premature closure
- blue：productive detour
- gray：unknown / no timestamp

### 10.3 Difficulty Map

不是量化長條圖，而是 thematic clusters：

```text
Main difficulties observed:
- Localization difficulty: E01, E03
- Compatibility risk: E02
- Verification difficulty: E04
```

每個 cluster 下方附 1–2 句解釋與 quote。

### 10.4 Detour Analysis

重點回答使用者真正關心的問題：

> 它有沒有繞路？這個繞路是有效探索，還是無效遊走？

可分為：

- Productive detour：原路不通 → 有新假設 → 縮小問題 → 繼續接近目標。
- Unproductive wandering：換方向但沒有新假設，問題越看越散。
- Workaround：不解根因，但有意識地降低風險或達成局部目標。

### 10.5 Recovery Pattern

輸出一段「恢復風格」：

> This agent tends to recover by reframing the problem and narrowing scope. It rarely asks for help, and it sometimes closes the loop before verification is fully established.

### 10.6 Outcome Claim Audit

不是驗證程式碼是否真的正確，而是檢查它怎麼說「我完成了」：

- 有沒有 caveat？
- 有沒有承認未驗證？
- 有沒有把 workaround 包裝成 root-cause fix？
- 有沒有過早成功宣稱？

---

## 11. Small-model analysis pipeline

因為 hackathon 限制 small models，MVP 應採取「small model + 結構化 prompt + 分段處理」而不是一次丟完整 trace。模型選型以 `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` 為主：它是 30B total parameters、約 3.5B active parameters per token 的 MoE 模型，剛好符合 Build Small Hackathon 的 ≤32B total-parameter 限制，且定位適合 coding / agentic / instruction-following 場景。

### 11.1 Pipeline

```text
Upload file
→ Parse JSONL
→ Extract narrative messages
→ Redact likely secrets
→ Chunk into windows
→ LLM pass 1: identify candidate difficulty episodes
→ LLM pass 2: classify each episode with codebook
→ LLM pass 3: synthesize field report
→ Render UI + export JSON/Markdown
```

### 11.2 Fallback heuristic

如果模型不可用或輸出 JSON 壞掉，使用 rule-based fallback：

- difficulty signals：`failed`, `error`, `not working`, `issue`, `problem`, `can't`, `cannot`, `unclear`, `ambiguous`, `however`, `instead`, `safer`, `fallback`, `retry`, `try another`, `need to`, `I should`, `looks like`
- strategy shift signals：`instead`, `rather than`, `safer approach`, `I'll try`, `switch`, `fallback`, `alternative`, `narrow`, `simpler`, `roll back`
- outcome signals：`done`, `fixed`, `resolved`, `should`, `verified`, `could not`, `need to verify`, `not able`

Fallback 只需要產生粗略 cards，不需要完美分類。

### 11.3 Model selection

**Primary / showcase model**

- Model: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16`
- Why it fits:
  - 30B total parameters, under the hackathon's ≤32B cap.
  - MoE architecture with about 3.5B active parameters per token, so the active compute is closer to a small model than to a dense 30B model.
  - Designed for English, coding languages, reasoning, chat, agent systems, RAG, and instruction-following tasks.
  - Strong conceptual fit: the app analyzes coding-agent narratives, so using an agentic / coding-oriented small model is part of the story.

**Runtime target**

- Deploy as a Hugging Face Gradio Space using **ZeroGPU**.
- Use `@spaces.GPU(size="xlarge", duration=...)` for the analysis function.
- Reason: BF16 30B weights are roughly 60GB before KV cache and runtime overhead, so ZeroGPU `large` may be tight; `xlarge` is safer for the demo.
- Caveat: ZeroGPU `xlarge` consumes 2× quota and can have longer queues. The app should therefore support a quick / fallback path.

**Fallback / quick mode**

Keep the implementation model-pluggable:

- Fallback model: `Qwen/Qwen3.5-9B`
  - Use when ZeroGPU queue is long, traces are short, or demo latency matters more than analysis depth.
- Rule-based fallback:
  - Always keep the heuristic path in `11.2`, so the app can still produce rough episode cards if the model fails or JSON parsing breaks.

**Language policy**

- Trace analysis should be English-first, because most coding-agent session messages are English and Nemotron 3 Nano's listed supported languages do not include Chinese.
- The UI can be bilingual.
- If Traditional Chinese output is required, prefer this pipeline:

```text
Nemotron → structured English JSON analysis → template-rendered Traditional Chinese summary
```

Do not rely on the main model to produce polished Traditional Chinese in the MVP.

**Important prompting constraint**

Do not ask the model to reveal hidden reasoning. The prompts should request structured fields and short evidence quotes from visible agent messages only.

---

## 12. LLM prompt templates

### 12.1 Episode extraction prompt

```text
You are analyzing a coding agent session log.
Only analyze the agent's visible narrative messages.
Do not infer hidden thoughts. Do not analyze raw tool outputs.

Task:
Identify difficulty episodes.
A difficulty episode is a span where the agent:
1. states or implies an intention,
2. encounters uncertainty, failure, risk, ambiguity, or blockage,
3. appraises the situation,
4. changes or maintains strategy,
5. attempts a resolution,
6. makes an outcome claim.

Return JSON only using this schema:
{ ...schema... }

Messages:
{messages}
```

### 12.2 Episode classification prompt

```text
Classify each difficulty episode using the codebook.
Prefer "unknown" if the evidence is weak.
Use short direct quotes as evidence.
Do not claim the agent actually understood something; say the agent reported, framed, claimed, or presented.

Codebook:
{codebook}

Episodes:
{episodes}
```

### 12.3 Report synthesis prompt

```text
Write a concise field-note style report for a developer who wants to understand how their coding agent handled difficulty.
Avoid quantitative leaderboard language.
Focus on:
- What the agent struggled with
- How it appraised the problem
- Whether it took productive detours
- How it recovered
- How it claimed completion
- Caveats and uncertainty

Use headings and episode IDs.
```

---

## 13. Privacy and safety design

### 13.1 Warning copy

Use this exact warning near upload:

> Agent traces can contain prompts, tool inputs, command outputs, local file paths, screenshots, secrets, private source code, and personal data. Redact before uploading. This app analyzes only visible agent narrative messages by default and does not need raw tool outputs.

### 13.2 Redaction MVP

Regex redactions:

- API keys / tokens common patterns
- `Authorization: Bearer ...`
- GitHub tokens: `ghp_`, `github_pat_`
- OpenAI / HF tokens if recognizable
- emails
- absolute local paths, optional
- URLs with query strings, optional
- long base64-like strings

### 13.3 Storage policy

MVP should default to:

- Do not persist uploaded traces.
- Delete temp files after analysis if feasible.
- Allow user to download redacted narrative only.
- Do not publish trace unless user explicitly chooses to.

---

## 14. Implementation outline

### 14.1 Suggested file structure

```text
.
├── app.py
├── analyzer.py
├── parser.py
├── redaction.py
├── prompts.py
├── schemas.py
├── report_renderer.py
├── requirements.txt
├── README.md
└── examples/
    └── sample_trace_redacted.jsonl
```

### 14.2 `parser.py`

Responsibilities:

- Load `.jsonl`, `.json`, `.txt`.
- Detect likely agent type.
- Extract role, timestamp, content.
- Keep assistant narrative messages.
- Optionally include user prompts as context.
- Skip tool call contents by default.

Pseudo-code:

```python
def parse_trace(path, include_user_context=True, ignore_tool_calls=True):
    records = load_jsonl_or_text(path)
    messages = []
    for record in records:
        msg = normalize_record(record)
        if msg.role == "assistant" and msg.text:
            messages.append(msg)
        elif include_user_context and msg.role == "user":
            messages.append(msg)
    return messages
```

### 14.3 `analyzer.py`

Responsibilities:

- Chunk messages.
- Call the primary model (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16`) through ZeroGPU, or call the fallback model / heuristic path.
- Validate JSON.
- Fall back to heuristics.
- Merge overlapping episodes.

### 14.4 `report_renderer.py`

Responsibilities:

- Render markdown report.
- Render episode cards for Gradio.
- Export JSON.

### 14.5 `app.py`

Gradio Blocks layout:

```python
with gr.Blocks(title="Trace Field Notes") as demo:
    gr.Markdown(HERO_MD)
    with gr.Row():
        file = gr.File(label="Upload your agent session log")
        options = ...
    analyze_btn = gr.Button("Analyze my trace")
    report = gr.Markdown()
    episodes = gr.JSON()
    download = gr.File(label="Download redacted narrative")
```

### 14.6 `model_runtime.py`

Responsibilities:

- Load the primary model at module root level for ZeroGPU compatibility.
- Wrap the expensive analysis function with `@spaces.GPU(size="xlarge", duration=...)`.
- Provide a fallback path if model loading, generation, or JSON parsing fails.

Sketch:

```python
import spaces
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

PRIMARY_MODEL_ID = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16"
FALLBACK_MODEL_ID = "Qwen/Qwen3.5-9B"

tokenizer = AutoTokenizer.from_pretrained(
    PRIMARY_MODEL_ID,
    trust_remote_code=True,
)
model = AutoModelForCausalLM.from_pretrained(
    PRIMARY_MODEL_ID,
    torch_dtype=torch.bfloat16,
    trust_remote_code=True,
).to("cuda")

@spaces.GPU(size="xlarge", duration=180)
def run_primary_model(messages, max_new_tokens=2048):
    # Build chat template, generate JSON, validate downstream.
    ...
```

Implementation note: this is a sketch, not guaranteed final code. Codex should test model loading on the actual Space and adjust memory settings, max tokens, or fallback behavior as needed.

---

## 15. MVP scope

### Must have

- Gradio Space UI.
- File upload.
- Clear tutorial for Codex / Claude Code / Pi local session folders.
- Privacy warning + basic redaction.
- Ignore tool-call contents by default.
- Extract assistant narrative messages.
- Identify difficulty episodes.
- Classify difficulty / appraisal / detour / resolution / recovery / outcome claim.
- Render readable field-note report.
- Export structured JSON.
- Provide copyable agents.md prompt for Codex / Claude Code.

### Should have

- Sample trace button.
- Download report as Markdown.
- Duration labels if timestamps exist.
- “Productive detour vs wandering” section.
- “Completion claim audit” section.

### Nice to have

- Compare two traces side-by-side.
- Load public HF dataset / bucket trace URL.
- Share redacted analysis report to dataset or gist.
- Custom visual timeline.
- Blog/report generator for Field Notes badge.

---

## 16. Demo script

1. Open the Space.
2. Show the hero: “upload an agent session log; see how the agent got stuck and recovered.”
3. Show where traces live:
   - Codex: `~/.codex/sessions`
   - Claude Code: `~/.claude/projects`
4. Upload a redacted `.jsonl` trace.
5. App shows:
   - Executive summary
   - Timeline of difficulty episodes
   - Detour analysis
   - Recovery pattern
   - Outcome claim audit
6. Show the copyable prompt for Codex / Claude Code to call the Space through `agents.md`.
7. End with the core message:

> We do not just ask whether an agent succeeded. We look at how it handled difficulty.

---

## 17. Suggested README pitch

```markdown
# Trace Field Notes

Trace Field Notes turns coding-agent session logs into qualitative field reports.

Upload a Codex, Claude Code, or Pi Agent JSONL trace. The app ignores raw tool telemetry by default and analyzes only the agent's visible narrative messages: what it planned, where it got stuck, how it detoured, how it recovered, and how it claimed completion.

Built for the Build Small Hackathon with NVIDIA Nemotron 3 Nano 30B-A3B under the 32B total-parameter limit and deployed as a Gradio Space on Hugging Face ZeroGPU.
```

---

## 18. Source references

- Build Small Hackathon page: https://huggingface.co/build-small-hackathon
- NVIDIA Nemotron 3 Nano 30B-A3B BF16 model card: https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16
- Hugging Face ZeroGPU docs: https://huggingface.co/docs/hub/en/spaces-zerogpu
- Hugging Face Agent Traces docs: https://huggingface.co/docs/hub/agent-traces
- Hugging Face Spaces as Agent Tools docs: https://huggingface.co/docs/hub/spaces-agents
- Hugging Face changelog for Spaces agents.md: https://huggingface.co/changelog/spaces-agents-md

---

## 19. Codex handoff prompt

Use this prompt to ask Codex to implement the MVP:

```text
Build a Hugging Face Space Gradio app called Trace Field Notes.

Read the design doc in this repository. Implement the MVP only:
- app.py Gradio Blocks UI
- upload .jsonl/.json/.txt/.log
- parse Codex / Claude Code / Pi Agent session logs
- extract only assistant narrative messages and optional user prompts
- ignore tool-call contents by default
- redact likely secrets before analysis
- identify difficulty episodes
- classify episodes using the provided codebook
- render a field-note style report
- export structured JSON and downloadable Markdown

Do not implement leaderboard metrics. Do not analyze raw tool-call telemetry. The product is qualitative: difficulty, detour, recovery, and outcome-claim analysis.

Keep the code simple and hackathon-ready. Use `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` as the primary model on Hugging Face ZeroGPU xlarge, with `Qwen/Qwen3.5-9B` or the heuristic path as fallback so the app still works in demo mode.
```
