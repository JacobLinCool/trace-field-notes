/* ============================================================
   app.jsx — shell + landing, wired to the gradio.Server backend.
   Adapted from the designer's prototype: the demo's fake upload
   is replaced with a real file picker that calls /analyze_trace
   through @gradio/client; the tweaks panel is dropped and the
   theme is pinned to the dusk-survey dark mode.
   ============================================================ */

function BrandMark({ size = 34 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" aria-hidden="true" className="brandmark">
      <circle cx="20" cy="20" r="17" stroke="var(--edge-strong)" strokeWidth="1.2" />
      <path d="M8 24 C 14 16, 18 28, 24 18 S 32 12, 33 14" stroke="var(--ink-3)" strokeWidth="1" fill="none" strokeDasharray="1.5 3" />
      <path d="M6 20 C 13 10, 20 30, 27 16 S 34 14, 35 20" stroke="var(--accent)" strokeWidth="2" fill="none" strokeLinecap="round" />
      <circle cx="13" cy="20" r="2.4" fill="var(--tone-stable)" />
      <circle cx="22" cy="22.5" r="2.4" fill="var(--tone-partial)" />
      <circle cx="30" cy="17" r="2.4" fill="var(--tone-risk)" />
      <path d="M30 17 L30 9 L36 11 L30 13" fill="var(--accent)" />
    </svg>
  );
}

function TopBar() {
  return (
    <header className="topbar">
      <div className="topbar__brand">
        <BrandMark />
        <div className="topbar__word">
          <span className="topbar__name">Trace Field Notes</span>
          <span className="topbar__tag mono">narrative analysis for coding-agent traces</span>
        </div>
      </div>
      <div className="topbar__right mono">
        <span className="topbar__pill">narrative-only</span>
        <span className="topbar__pill">privacy-first</span>
      </div>
    </header>
  );
}

const ENGINES = [
  ["qwen", "Quick analysis", "Qwen3.5 9B"],
  ["nemotron", "Deeper analysis", "Nemotron 3 Nano 30B-A3B"],
  ["deterministic", "Rule-based", "no model, always on"],
];

function Toggle({ on, set, label, sub, locked }) {
  return (
    <button className={"toggle" + (on ? " toggle--on" : "") + (locked ? " toggle--locked" : "")}
      onClick={() => !locked && set(!on)} aria-pressed={on}>
      <span className="toggle__sw"><span className="toggle__knob" /></span>
      <span className="toggle__txt">
        <span className="toggle__label">{label}{locked ? " 🔒" : ""}</span>
        <span className="toggle__sub muted">{sub}</span>
      </span>
    </button>
  );
}

function LandingView({ onAnalyze, onSample, error }) {
  const [staged, setStaged] = React.useState(null); // { name, file }
  const [redact, setRedact] = React.useState(true);
  const [userCtx, setUserCtx] = React.useState(true);
  const [engine, setEngine] = React.useState("qwen");
  const [dragOver, setDragOver] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const fileRef = React.useRef(null);

  const chosen = ENGINES.find((e) => e[0] === engine) || ENGINES[2];
  const engineLabel = chosen[1] + ": " + chosen[2];

  function onFiles(list) {
    const f = list && list[0];
    if (f) setStaged({ name: f.name, file: f });
  }
  function pick() { if (fileRef.current) fileRef.current.click(); }
  function run() {
    if (!staged) return;
    onAnalyze({ file: staged.file, include_user_context: userCtx, redact_secrets: redact, analysis_engine: engine, engineLabel });
  }

  const AGENT_PROMPT = `Use this Space as a tool.
1. Read its /agents.md endpoint.
2. Find my latest local agent session log
   (Codex ~/.codex/sessions, Claude ~/.claude/projects).
3. Review and redact secrets before upload.
4. Upload the JSONL and request a narrative difficulty analysis.
5. Return the report. Do not publish the raw trace.`;

  return (
    <div className="landing">
      <TopBar />

      <section className="hero">
        <h1 className="hero__title">See how your coding agent<br /> got stuck, detoured, recovered<span className="hero__amp"> &amp; </span>claimed success.</h1>
        <p className="hero__sub">
          Upload a Codex, Claude Code, or Pi Agent session log. Trace Field Notes reads only the agent's
          <em> narrated</em> messages — what it planned, where it snagged, how it rerouted, and how honestly it called it done —
          and charts the session as a trail you can walk.
        </p>
      </section>

      <div className="privacy">
        <span className="privacy__mark">!</span>
        <p>
          Agent traces can carry prompts, command output, local paths, screenshots, secrets, and private code.
          <b> Review and redact before uploading or sharing.</b> This app analyzes only visible narrative messages and ignores raw tool telemetry by default.
        </p>
      </div>

      {error ? (
        <div className="privacy" style={{ borderColor: "var(--tone-risk)", borderLeftColor: "var(--tone-risk)" }}>
          <span className="privacy__mark" style={{ background: "var(--tone-risk)" }}>×</span>
          <p><b>Analysis failed.</b> {error}</p>
        </div>
      ) : null}

      <div className="landing__grid">
        {/* LEFT: upload */}
        <div className="panel card card--raised">
          <SectionHead kicker="Step 01" title="Bring a trace" />
          <input ref={fileRef} type="file" accept=".jsonl,.json,.txt,.log" style={{ display: "none" }}
            onChange={(e) => onFiles(e.target.files)} />
          <div
            className={"drop" + (dragOver ? " drop--over" : "") + (staged ? " drop--staged" : "")}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); onFiles(e.dataTransfer.files); }}
            onClick={pick}
            role="button" tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") pick(); }}
          >
            {staged ? (
              <div className="drop__staged">
                <span className="drop__file mono">{staged.name}</span>
                <span className="label">staged · click Analyze</span>
              </div>
            ) : (
              <div className="drop__empty">
                <div className="drop__icon">⤓</div>
                <span className="drop__title">Drop a <code>.jsonl</code> trace</span>
                <span className="muted">or click to choose · .json .txt .log accepted</span>
              </div>
            )}
          </div>

          <div className="opts">
            <Toggle on={redact} set={setRedact} label="Redact likely secrets" sub="emails, tokens, keys, paths" />
            <Toggle on={userCtx} set={setUserCtx} label="Include user context" sub="user prompts as framing" />
            <Toggle on={true} set={() => {}} locked label="Ignore tool contents" sub="locked for this release" />
          </div>

          <div className="engine">
            <Label>Analysis engine</Label>
            <div className="engine__opts">
              {ENGINES.map(([key, name, detail]) => (
                <button key={key}
                  className={"engine__opt" + (engine === key ? " engine__opt--on" : "")}
                  onClick={() => setEngine(key)}>
                  <span className="engine__name">{name}</span>
                  <span className="engine__detail mono">{detail}</span>
                </button>
              ))}
            </div>
            <p className="engine__note muted">Quick and Deeper run a small model on the Space GPU. Rule-based needs no model and never fails.</p>
          </div>

          <div className="panel__actions">
            <button className="btn btn--primary" disabled={!staged} onClick={run}>
              Analyze my trace
            </button>
            <button className="btn" onClick={() => onSample("short")}>Sample · short</button>
            <button className="btn" onClick={() => onSample("long")}>Sample · long</button>
          </div>
        </div>

        {/* RIGHT: guide */}
        <div className="guide">
          <div className="panel card">
            <SectionHead kicker="Step 00" title="Find your session log" />
            <table className="paths">
              <tbody>
                {[
                  ["Codex", "~/.codex/sessions"],
                  ["Claude Code", "~/.claude/projects"],
                  ["Pi Agent", "~/.pi/agent/sessions"],
                ].map(([a, p]) => (
                  <tr key={a}>
                    <td className="paths__agent">{a}</td>
                    <td className="paths__path mono">{p}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="panel card">
            <div className="agentcall__hd">
              <SectionHead kicker="Hands-free" title="Let the agent call it" />
              <button className="btn btn--sm btn--ghost" onClick={() => {
                try { navigator.clipboard && navigator.clipboard.writeText(AGENT_PROMPT); } catch (e) {}
                setCopied(true); setTimeout(() => setCopied(false), 1400);
              }}>
                {copied ? "copied ✓" : "copy prompt"}
              </button>
            </div>
            <p className="agentcall__blurb">Using Codex or Claude Code? Point it at this Space's <span className="mono">agents.md</span>. It finds your latest log, redacts it, uploads, and returns the report.</p>
            <pre className="agentcall__pre mono">{AGENT_PROMPT}</pre>
          </div>

          <div className="getrow">
            {[
              ["Elevation trail", "every snag as a waypoint"],
              ["Detour read", "exploration vs wandering"],
              ["Closeout audit", "honest, or overclaimed?"],
            ].map(([t, s]) => (
              <div className="getrow__item" key={t}>
                <span className="getrow__t">{t}</span>
                <span className="getrow__s muted">{s}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

const PIPELINE = [
  "Uploading the trace",
  "Extracting narrative messages",
  "Redacting likely secrets",
  "Charting difficulty episodes",
  "Classifying with the codebook",
  "Synthesizing field notes",
];

function Analyzing({ label, step }) {
  return (
    <div className="analyzing">
      <div className="analyzing__card card card--raised">
        <svg viewBox="0 0 320 120" className="analyzing__svg" aria-hidden="true">
          <line x1="20" y1="100" x2="300" y2="100" stroke="var(--rule)" strokeDasharray="2 6" />
          <path className="analyzing__trail"
            d="M20 96 C 70 60, 100 104, 150 70 S 230 30, 300 44"
            fill="none" stroke="var(--accent)" strokeWidth="2.6" strokeLinecap="round" />
          <circle className="analyzing__dot" r="4.5" fill="var(--accent)" />
        </svg>
        <Kicker>Surveying the trace · {label}</Kicker>
        <ul className="analyzing__steps">
          {PIPELINE.map((s, i) => (
            <li key={s} className={i < step ? "done" : i === step ? "active" : ""}>
              <span className="analyzing__tick mono">{i < step ? "✓" : i === step ? "…" : "·"}</span>{s}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function EmptyReport({ data, onReset }) {
  return (
    <div className="report">
      <ReportHeader data={data} />
      <section className="sec">
        <div className="card" style={{ padding: "28px 30px" }}>
          <SectionHead kicker="No episode surfaced" title="No explicit difficulty episode was strong enough to classify" />
          <p className="sec-head__sub" style={{ maxWidth: "70ch" }}>
            The trace yielded {data.narrative_message_count} visible narrative messages, but none carried clear
            self-reported blockage, detour, or recovery language. That does not prove the session was trouble-free —
            only that the narrative did not say so. Try the redacted-narrative export to read it yourself.
          </p>
          <div style={{ marginTop: 18 }}>
            <button className="btn btn--sm btn--ghost" onClick={onReset}>← Analyze another trace</button>
          </div>
        </div>
      </section>
    </div>
  );
}

function App() {
  const [stage, setStage] = React.useState("landing"); // landing | analyzing | report
  const [data, setData] = React.useState(null);
  const [engineLabel, setEngineLabel] = React.useState("");
  const [error, setError] = React.useState("");
  const [step, setStep] = React.useState(0);

  async function analyze({ file, include_user_context, redact_secrets, analysis_engine, engineLabel }) {
    setError("");
    setEngineLabel(engineLabel || analysis_engine);
    setStep(0);
    setStage("analyzing");
    window.scrollTo({ top: 0 });
    try {
      const g = window.__gradio;
      if (!g) throw new Error("Client is still loading — reload the page and try again.");
      const client = await g.clientPromise;
      const sub = client.submit("/analyze_trace", {
        trace_file: g.handle_file(file),
        include_user_context: !!include_user_context,
        redact_secrets: !!redact_secrets,
        analysis_engine,
      });
      let result = null;
      for await (const msg of sub) {
        if (msg.type === "data") {
          const p = Array.isArray(msg.data) ? msg.data[0] : msg.data;
          if (p && typeof p === "object") {
            if (typeof p.step === "number") setStep(p.step);
            if (p.result) result = p.result;
          }
        } else if (msg.type === "status") {
          if (msg.stage === "error") throw new Error(msg.message || "The analyzer failed on the server.");
          if (msg.stage === "generating") setStep((s) => (s < 1 ? 1 : s));
        }
      }
      if (!result || typeof result !== "object") throw new Error("The analyzer returned no result.");
      setStep(PIPELINE.length);
      setData(result);
      setStage("report");
    } catch (e) {
      setError(String((e && e.message) || e));
      setStage("landing");
    }
    window.scrollTo({ top: 0 });
  }

  function loadSample(key) {
    const base = key === "short" ? window.TFN.SHORT : window.TFN.LONG;
    setError("");
    setEngineLabel(base.engine);
    setData(base);
    setStage("report");
    window.scrollTo({ top: 0 });
  }

  function reset() { setStage("landing"); setData(null); window.scrollTo({ top: 0 }); }

  const reportData = data ? Object.assign({}, data, { engine: engineLabel || data.engine }) : null;
  const hasEpisodes = reportData && reportData.episodes && reportData.episodes.length;

  return (
    <div className="app-root" data-theme="dark" data-density="regular" data-voice="journal">
      <div className="backdrop"><div className="grain" /><TopoBackground /></div>
      <div className="page">
        {stage === "landing" && <LandingView onAnalyze={analyze} onSample={loadSample} error={error} />}
        {stage === "analyzing" && <Analyzing label={engineLabel} step={step} />}
        {stage === "report" && (
          <div className="report-wrap">
            <button className="report-back btn btn--sm btn--ghost" onClick={reset}>← New trace</button>
            {hasEpisodes
              ? <ReportView data={reportData} variant="trail" onReset={reset} />
              : <EmptyReport data={reportData} onReset={reset} />}
            <footer className="foot">
              <span className="mono">Trace Field Notes</span>
              <span className="muted">Qualitative narrative analysis · we report what the agent said, not whether its code is correct.</span>
            </footer>
          </div>
        )}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
