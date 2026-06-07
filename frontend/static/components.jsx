/* ============================================================
   atoms.jsx — shared primitives + topo background
   ============================================================ */

// ---- deterministic topo contour generator ----
function _noise(a, seed) {
  return (
    Math.sin(a * 3 + seed) * 0.45 +
    Math.sin(a * 5 + seed * 1.7) * 0.28 +
    Math.sin(a * 2 + seed * 0.6) * 0.5 +
    Math.sin(a * 7 + seed * 2.3) * 0.16
  );
}
function _blob(cx, cy, r, seed, amp) {
  const N = 80;
  let d = "";
  for (let i = 0; i <= N; i++) {
    const t = (i / N) * Math.PI * 2;
    const rr = r * (1 + amp * _noise(t, seed));
    const x = cx + rr * Math.cos(t);
    const y = cy + rr * Math.sin(t) * 0.82;
    d += (i === 0 ? "M" : "L") + x.toFixed(1) + " " + y.toFixed(1) + " ";
  }
  return d + "Z";
}

function TopoBackground() {
  const peaks = [
    { cx: 250, cy: 230, seed: 1.2, count: 11, base: 26, step: 34, peakAt: 3 },
    { cx: 1160, cy: 640, seed: 4.7, count: 13, base: 24, step: 32, peakAt: 4 },
    { cx: 760, cy: 120, seed: 8.1, count: 7, base: 30, step: 40, peakAt: 1 },
  ];
  return (
    <svg viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      {peaks.map((p, pi) =>
        Array.from({ length: p.count }).map((_, i) => {
          const r = p.base + i * p.step;
          const amp = 0.05 + i * 0.012;
          const strong = i === p.peakAt;
          return (
            <path
              key={pi + "-" + i}
              d={_blob(p.cx, p.cy, r, p.seed + i * 0.13, amp)}
              fill="none"
              stroke={strong ? "var(--topo-stroke-strong)" : "var(--topo-stroke)"}
              strokeWidth={strong ? 1.4 : 0.9}
            />
          );
        })
      )}
    </svg>
  );
}

// ---- tone helpers ----
function toneOf(recovery) {
  return (window.TFN.TONE_OF[recovery]) || "unknown";
}
function toneColor(tone) {
  return "var(--tone-" + tone + ")";
}

// ---- small atoms ----
function Kicker({ children }) {
  return <div className="kicker">{children}</div>;
}

function Label({ children, accent, style }) {
  return <div className={"label" + (accent ? " label--accent" : "")} style={style}>{children}</div>;
}

function ToneDot({ tone, size = 10 }) {
  return (
    <span
      className="tone-dot"
      style={{ background: toneColor(tone), color: toneColor(tone), width: size, height: size }}
    />
  );
}

// codebook chip: pass field + code
function CodeChip({ field, code, withDotTone }) {
  const label = (window.TFN.CODEBOOK[field] && window.TFN.CODEBOOK[field][code]) || code;
  return (
    <span className="chip" title={field.replace(/_/g, " ")}>
      {withDotTone ? <span className="dot" style={{ background: toneColor(withDotTone) }} /> : null}
      {label}
    </span>
  );
}

function Stamp({ tone, children }) {
  return (
    <span className="stamp" style={{ color: toneColor(tone) }}>
      {children}
    </span>
  );
}

// section header used across the report
function SectionHead({ index, kicker, title, sub }) {
  return (
    <div className="sec-head">
      <div className="sec-head__top">
        {index ? <span className="sec-head__no mono">{index}</span> : null}
        <Kicker>{kicker}</Kicker>
      </div>
      <h2 className="sec-head__title">{title}</h2>
      {sub ? <p className="sec-head__sub">{sub}</p> : null}
    </div>
  );
}

Object.assign(window, {
  TopoBackground, toneOf, toneColor,
  Kicker, Label, ToneDot, CodeChip, Stamp, SectionHead,
});

/* ============================================================
   trailmap.jsx — elevation-profile trail map + episode detail
   x = progress through the session, y = risk / exposure.
   The agent's journey climbs toward hazard.
   ============================================================ */

const ELEV = { stable: 0.12, detour: 0.44, iterative: 0.52, partial: 0.64, risk: 0.93, unknown: 0.30 };

const VBW = 1000, VBH = 360;
const PAD = { l: 116, r: 96, t: 48, b: 60 };

function _layout(episodes) {
  const n = episodes.length;
  const innerW = VBW - PAD.l - PAD.r;
  const innerH = VBH - PAD.t - PAD.b;
  const baseY = VBH - PAD.b;
  return episodes.map((ep, i) => {
    const tone = toneOf(ep.recovery_pattern);
    const x = PAD.l + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);
    const jitter = ((i % 2) * 2 - 1) * 0.015;
    const elev = Math.min(0.97, Math.max(0.06, ELEV[tone] + jitter));
    const y = baseY - elev * innerH;
    return { ep, tone, x, y, fx: (x / VBW) * 100, fy: (y / VBH) * 100, elev };
  });
}

function _smoothPath(pts) {
  if (pts.length === 1) return `M ${pts[0].x} ${pts[0].y}`;
  let d = `M ${pts[0].x} ${pts[0].y}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] || p2;
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
  }
  return d;
}

function TrailMap({ episodes, selectedId, onSelect }) {
  const pts = _layout(episodes);
  const baseY = VBH - PAD.b;
  const line = _smoothPath(pts);
  const area = `${line} L ${pts[pts.length - 1].x} ${baseY} L ${pts[0].x} ${baseY} Z`;
  const gridY = [0.25, 0.5, 0.75, 1].map((f) => baseY - f * (VBH - PAD.t - PAD.b));

  return (
    <div className="trail">
      <div className="trail__chrome">
        <div className="trail__axis-y">
          <span>Hazard</span><span>Exposure</span><span>On-route</span>
        </div>
        <div className="trail__plot">
          <svg viewBox={`0 0 ${VBW} ${VBH}`} preserveAspectRatio="xMidYMid meet" className="trail__svg">
            <defs>
              <linearGradient id="hypso" x1="0" y1={PAD.t} x2="0" y2={baseY} gradientUnits="userSpaceOnUse">
                <stop offset="0%" stopColor="var(--tone-risk)" stopOpacity="0.20" />
                <stop offset="45%" stopColor="var(--tone-partial)" stopOpacity="0.12" />
                <stop offset="100%" stopColor="var(--tone-stable)" stopOpacity="0.08" />
              </linearGradient>
            </defs>
            {/* elevation grid */}
            {gridY.map((y, i) => (
              <line key={i} x1={PAD.l} y1={y} x2={VBW - PAD.r} y2={y}
                stroke="var(--rule)" strokeWidth="1" strokeDasharray="2 6" />
            ))}
            <line x1={PAD.l} y1={baseY} x2={VBW - PAD.r} y2={baseY} stroke="var(--rule-strong)" strokeWidth="1.2" />
            {/* hypsometric fill + ridge line */}
            <path d={area} fill="url(#hypso)" />
            <path d={line} fill="none" stroke="var(--ink-3)" strokeWidth="2.4"
              strokeLinecap="round" strokeLinejoin="round" />
            {/* drop stems + waypoint nodes (selectable) */}
            {pts.map((p) => {
              const sel = p.ep.episode_id === selectedId;
              return (
                <g key={p.ep.episode_id} className="trail__node" onClick={() => onSelect(p.ep.episode_id)}>
                  <line x1={p.x} y1={p.y} x2={p.x} y2={baseY} stroke={toneColor(p.tone)} strokeWidth="1" strokeOpacity="0.4" />
                  <circle cx={p.x} cy={p.y} r={sel ? 13 : 9} fill="var(--paper-3)"
                    stroke={toneColor(p.tone)} strokeWidth={sel ? 4 : 3} />
                  <circle cx={p.x} cy={p.y} r="3" fill={toneColor(p.tone)} />
                </g>
              );
            })}
          </svg>
          {/* HTML waypoint flags positioned over the SVG */}
          {pts.map((p, i) => {
            const sel = p.ep.episode_id === selectedId;
            const above = p.fy > 46;
            const edge = i === 0 ? " wp--first" : i === pts.length - 1 ? " wp--last" : "";
            return (
              <button
                key={p.ep.episode_id}
                className={"wp" + (sel ? " wp--sel" : "") + (above ? " wp--above" : " wp--below") + edge}
                style={{ left: p.fx + "%", top: p.fy + "%", "--tone": toneColor(p.tone) }}
                onClick={() => onSelect(p.ep.episode_id)}
              >
                <span className="wp__id mono">{p.ep.episode_id}</span>
                <span className="wp__title">{p.ep.title}</span>
                <span className="wp__dur mono">{p.ep.message_span.duration_label}</span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="trail__xaxis">
        <span className="mono">start · {episodes[0].message_span.start_time}</span>
        <span className="label">progress through session →</span>
        <span className="mono">end · {episodes[episodes.length - 1].message_span.end_time}</span>
      </div>
    </div>
  );
}

// ---- Episode detail (used by both layouts) ----
function EpisodeDetail({ ep }) {
  if (!ep) return null;
  const tone = toneOf(ep.recovery_pattern);
  const tm = window.TFN.TONE_META[tone];
  return (
    <div className="epd card card--raised" style={{ "--tone": toneColor(tone) }}>
      <div className="epd__band" />
      <div className="epd__head">
        <div className="epd__id">
          <span className="mono epd__no">{ep.episode_id}</span>
          <ToneDot tone={tone} size={12} />
        </div>
        <div>
          <h3 className="epd__title">{ep.title}</h3>
          <div className="epd__meta mono">
            {tm.label} · {ep.message_span.duration_label} · {ep.message_span.start_time}–{ep.message_span.end_time}
          </div>
        </div>
      </div>

      <div className="epd__flow">
        {[
          ["Intention", ep.initial_intention],
          ["Difficulty", ep.reported_difficulty],
          ["Reroute", ep.strategy_after],
        ].map(([k, v]) => (
          <div className="epd__step" key={k}>
            <span className="label">{k}</span>
            <p>{v}</p>
          </div>
        ))}
      </div>

      <hr className="rule--dashed" />

      <div className="epd__codes">
        <CodeChip field="difficulty_type" code={ep.difficulty_type} />
        <CodeChip field="appraisal" code={ep.appraisal} />
        <CodeChip field="detour_type" code={ep.detour_type} />
        <CodeChip field="resolution_mode" code={ep.resolution_mode} />
        <CodeChip field="recovery_pattern" code={ep.recovery_pattern} withDotTone={tone} />
        <CodeChip field="outcome_claim" code={ep.outcome_claim} />
      </div>

      {ep.evidence_quotes && ep.evidence_quotes.length ? (
        <div className="epd__quotes">
          <span className="label">Evidence — agent's own words</span>
          {ep.evidence_quotes.map((q, i) => (
            <blockquote key={i} className="quote">{q}</blockquote>
          ))}
        </div>
      ) : null}

      <div className="epd__memo">
        <span className="label label--accent">Analyst memo</span>
        <p>{ep.analyst_memo}</p>
      </div>
    </div>
  );
}

// ---- Ledger (vertical) timeline variant ----
function LedgerTimeline({ episodes, selectedId, onSelect }) {
  return (
    <div className="ledger">
      {episodes.map((ep) => {
        const tone = toneOf(ep.recovery_pattern);
        const sel = ep.episode_id === selectedId;
        return (
          <button key={ep.episode_id}
            className={"ledger__row" + (sel ? " ledger__row--sel" : "")}
            style={{ "--tone": toneColor(tone) }}
            onClick={() => onSelect(ep.episode_id)}>
            <span className="ledger__rail"><ToneDot tone={tone} size={13} /></span>
            <span className="ledger__id mono">{ep.episode_id}</span>
            <span className="ledger__main">
              <span className="ledger__title">{ep.title}</span>
              <span className="ledger__sub">{window.TFN.CODEBOOK.difficulty_type[ep.difficulty_type]} → {window.TFN.CODEBOOK.recovery_pattern[ep.recovery_pattern]}</span>
            </span>
            <span className="ledger__dur mono">{ep.message_span.duration_label}</span>
          </button>
        );
      })}
    </div>
  );
}

Object.assign(window, { TrailMap, EpisodeDetail, LedgerTimeline });

/* ============================================================
   report.jsx — the field report: verdict, trail, analysis sections
   ============================================================ */

const HONESTY = {
  resolved_with_confidence: { tone: "stable", note: "Clear, committed claim." },
  resolved_with_caveat:     { tone: "stable", note: "States its own limits." },
  partially_resolved:       { tone: "partial", note: "Honest partial." },
  not_resolved:             { tone: "partial", note: "Admits it's unresolved." },
  needs_verification:       { tone: "partial", note: "Flags a verification gap." },
  uncertain_but_proceeding: { tone: "partial", note: "Proceeds under stated uncertainty." },
  premature_success_claim:  { tone: "risk", note: "Claim outruns the evidence." },
  unknown:                  { tone: "unknown", note: "—" },
};


// download helper for the export buttons (no-op if the backend didn't supply text)
function dl(text, filename, mime) {
  if (!text) return;
  const blob = new Blob([text], { type: mime || "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; document.body.appendChild(a); a.click();
  a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function ReportHeader({ data }) {
  return (
    <div className="rhead">
      <div className="rhead__tag mono">FIELD LOG № {data.agent_type_guess === "codex" ? "C-01" : "CC-04"}</div>
      <div className="rhead__main">
        <Label accent>Trace</Label>
        <h1 className="rhead__file mono">{data.trace_title}</h1>
      </div>
      <dl className="rhead__grid">
        {[
          ["Agent", data.agent_type_guess.replace("_", " ")],
          ["Captured", data.captured],
          ["Scope", "narrative msgs only"],
          ["Messages", String(data.narrative_message_count)],
          ["Engine", data.engine],
          ["Redactions", String(data.redaction_count)],
        ].map(([k, v]) => (
          <div key={k} className="rhead__cell">
            <dt className="label">{k}</dt>
            <dd className="mono">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function ModelStatus({ data }) {
  const notes = (data.privacy_notes || []).filter((note) => String(note).startsWith("Model assist"));
  if (!notes.length) return null;
  return (
    <div className="privacy model-status">
      <span className="privacy__mark">!</span>
      <p><b>Model assist fell back to the rule-based analyzer.</b> {notes.join(" ")}</p>
    </div>
  );
}

function Verdict({ data }) {
  const v = data.verdict;
  const tm = window.TFN.TONE_META[v.tone];
  const honestyWord = v.honesty === "overclaimed" ? "Overclaimed close-out"
    : v.honesty === "candid" ? "Candid close-out" : "Mixed close-out";
  return (
    <div className="verdict card card--raised" style={{ "--tone": toneColor(v.tone) }}>
      <div className="verdict__band" />
      <div className="verdict__left">
        <Kicker>Trail verdict</Kicker>
        <h2 className="verdict__headline">{v.headline}</h2>
        <p className="verdict__detail">{v.detail}</p>
        <div className="verdict__stamps">
          <Stamp tone={v.tone}>{honestyWord}</Stamp>
        </div>
      </div>
      <div className="verdict__right">
        <div className="verdict__gauge" style={{ "--tone": toneColor(v.tone) }}>
          <span className="verdict__gauge-label label">Recovery read</span>
          <span className="verdict__gauge-val">{tm.rating}</span>
          <span className="verdict__gauge-blurb">{tm.blurb}</span>
        </div>
        <div className="verdict__stats">
          <div><span className="verdict__num mono">{data.episodes.length}</span><span className="label">episodes</span></div>
          <div><span className="verdict__num mono">{data.duration_total}</span><span className="label">on trail</span></div>
        </div>
      </div>
    </div>
  );
}

function Legend() {
  const order = ["stable", "detour", "iterative", "partial", "risk", "unknown"];
  const M = window.TFN.TONE_META;
  return (
    <div className="legend">
      <span className="label">Waypoint key</span>
      <div className="legend__items">
        {order.map((t) => (
          <span className="legend__item" key={t}>
            <ToneDot tone={t} size={11} />
            <span className="legend__txt"><b>{M[t].label}</b> · {M[t].rating}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function TrailSection({ data, variant, selectedId, setSelectedId }) {
  const ep = data.episodes.find((e) => e.episode_id === selectedId) || data.episodes[0];
  return (
    <section className="sec">
      <SectionHead index="01" kicker="Journey · elevation profile"
        title="Where the route climbed into hazard"
        sub="Each waypoint is a difficulty episode. The line rises with risk — open ground low, exposed claims high. Tap a waypoint to read it." />
      <div className="card trail-card">
        {variant === "ledger"
          ? <LedgerTimeline episodes={data.episodes} selectedId={ep.episode_id} onSelect={setSelectedId} />
          : <TrailMap episodes={data.episodes} selectedId={ep.episode_id} onSelect={setSelectedId} />}
        <hr className="rule" />
        <Legend />
      </div>
      <EpisodeDetail ep={ep} />
    </section>
  );
}

function DifficultyMap({ data }) {
  const clusters = {};
  data.episodes.forEach((e) => {
    (clusters[e.difficulty_type] = clusters[e.difficulty_type] || []).push(e);
  });
  const CB = window.TFN.CODEBOOK.difficulty_type;
  const entries = Object.entries(clusters).sort((a, b) => b[1].length - a[1].length);
  return (
    <section className="sec">
      <SectionHead index="02" kicker="Terrain" title="What kind of ground it was"
        sub="Difficulties grouped by type — the recurring terrain, not a leaderboard." />
      <div className="dmap">
        {entries.map(([type, eps]) => {
          const quote = (eps.find((e) => e.evidence_quotes && e.evidence_quotes.length) || {}).evidence_quotes;
          return (
            <div className="dmap__cell card" key={type}>
              <div className="dmap__hd">
                <span className="dmap__type">{CB[type] || type}</span>
                <span className="dmap__ids mono">{eps.map((e) => e.episode_id).join(" · ")}</span>
              </div>
              {quote ? <blockquote className="quote quote--sm">{quote[0]}</blockquote> : <p className="muted">No short evidence quote.</p>}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function DetourAnalysis({ data }) {
  const groups = { yes: [], mixed: [], no: [] };
  data.episodes.forEach((e) => { if (groups[e.productive_detour]) groups[e.productive_detour].push(e); });
  const defs = [
    ["yes", "Productive detours", "Off-route, but a better line emerged.", "detour"],
    ["mixed", "Mixed", "A reroute with real upside and a loose end.", "partial"],
    ["no", "Wandering / workaround", "Movement without a new line on the problem.", "risk"],
  ];
  return (
    <section className="sec">
      <SectionHead index="03" kicker="Route choices" title="Detours — exploration or wandering?"
        sub="The question that actually matters: when it left the planned path, did it find a better one?" />
      <div className="detour">
        {defs.map(([key, title, blurb, tone]) => (
          <div className="detour__col card" key={key} style={{ "--tone": toneColor(tone) }}>
            <div className="detour__hd">
              <ToneDot tone={tone} size={11} />
              <span className="detour__title">{title}</span>
              <span className="detour__count mono">{groups[key].length}</span>
            </div>
            <p className="detour__blurb">{blurb}</p>
            <div className="detour__list">
              {groups[key].length ? groups[key].map((e) => (
                <div className="detour__ep" key={e.episode_id}>
                  <span className="mono detour__epid">{e.episode_id}</span>
                  <CodeChip field="detour_type" code={e.detour_type} />
                </div>
              )) : <span className="muted detour__none">None observed.</span>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function RecoveryPattern({ data }) {
  const p = data.overall_patterns;
  const rows = [
    ["Difficulty style", p.difficulty_style],
    ["Detour style", p.detour_style],
    ["Recovery style", p.recovery_style],
    ["Standing caveat", p.risk_or_caveat],
  ];
  return (
    <section className="sec">
      <SectionHead index="04" kicker="Field naturalist's read" title="How this agent travels"
        sub="A behavioral read across the whole session — its habits under difficulty." />
      <div className="recov card card--raised">
        {rows.map(([k, v], i) => (
          <div className="recov__row" key={k}>
            <span className="recov__no mono">{String(i + 1).padStart(2, "0")}</span>
            <span className="label recov__k">{k}</span>
            <p className="recov__v">{v}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function OutcomeAudit({ data }) {
  const CB = window.TFN.CODEBOOK.outcome_claim;
  return (
    <section className="sec">
      <SectionHead index="05" kicker="Closeout audit" title="What it said when it called it done"
        sub="Not whether the code is correct — whether the agent's claim matches its own evidence." />
      <div className="audit card">
        {data.episodes.map((e) => {
          const h = HONESTY[e.outcome_claim] || HONESTY.unknown;
          return (
            <div className="audit__row" key={e.episode_id} style={{ "--tone": toneColor(h.tone) }}>
              <div className="audit__rail"><span className="mono">{e.episode_id}</span><ToneDot tone={h.tone} size={11} /></div>
              <div className="audit__body">
                <div className="audit__claim">
                  <span className="audit__verb">{CB[e.outcome_claim] || e.outcome_claim}</span>
                  <span className="audit__note">{h.note}</span>
                </div>
                {e.evidence_quotes && e.evidence_quotes.length ? (
                  <blockquote className="quote quote--sm">{e.evidence_quotes[e.evidence_quotes.length - 1]}</blockquote>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function PrivacyExports({ data, onReset }) {
  return (
    <section className="sec">
      <div className="px">
        <div className="px__notes card">
          <SectionHead kicker="Privacy ledger" title={`${data.redaction_count} item${data.redaction_count === 1 ? "" : "s"} redacted before analysis`} />
          <ul className="px__list">
            {data.privacy_notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </div>
        <div className="px__exports card card--raised">
          <Label accent>Take it with you</Label>
          <p className="px__blurb">Export the redacted narrative and the structured findings. The raw trace never leaves your machine.</p>
          <div className="px__btns">
            <button className="btn btn--sm" onClick={() => dl(data.exports && data.exports.narrative_md, (data.trace_title||"trace")+"-redacted.md", "text/markdown")}><span>↓</span> Redacted narrative .md</button>
            <button className="btn btn--sm" onClick={() => dl(data.exports && data.exports.report_md, (data.trace_title||"trace")+"-field-report.md", "text/markdown")}><span>↓</span> Field report .md</button>
            <button className="btn btn--sm" onClick={() => dl(data.exports && data.exports.episodes_json, (data.trace_title||"trace")+"-episodes.json", "application/json")}><span>↓</span> Episodes .json</button>
          </div>
          <hr className="rule--dashed" />
          <button className="btn btn--ghost btn--sm" onClick={onReset}>← Analyze another trace</button>
        </div>
      </div>
    </section>
  );
}

function ReportView({ data, variant, onReset }) {
  const [selectedId, setSelectedId] = React.useState(
    () => (data.verdict.tone === "risk"
      ? (data.episodes.find((e) => toneOf(e.recovery_pattern) === "risk") || data.episodes[0]).episode_id
      : data.episodes[0].episode_id)
  );
  React.useEffect(() => {
    setSelectedId(data.episodes[0].episode_id);
  }, [data]);
  return (
    <div className="report">
      <ReportHeader data={data} />
      <ModelStatus data={data} />
      <Verdict data={data} />
      <TrailSection data={data} variant={variant} selectedId={selectedId} setSelectedId={setSelectedId} />
      <DifficultyMap data={data} />
      <DetourAnalysis data={data} />
      <RecoveryPattern data={data} />
      <OutcomeAudit data={data} />
      <PrivacyExports data={data} onReset={onReset} />
    </div>
  );
}

Object.assign(window, { ReportView });
