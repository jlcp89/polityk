// charts.jsx — chart primitives for polityc

// — Density / violin / ridge / bar+CI / dotplot ————————————————

// Renders a single posterior for one candidate. `style` ∈ violin | ridge | bar | dot
function Posterior({ c, width = 280, height = 64, style = 'violin', ciLevel = 80,
                     xMin = 0, xMax = 30, color, onClick, active = false, dim = false }) {
  const col = color || c.color;
  const dens = window.density(c.mean, c.sd, c.skew, xMin, xMax, 100);
  const ci = window.intervals(c);
  const lo = ciLevel === 80 ? ci.q10 : ci.q025;
  const hi = ciLevel === 80 ? ci.q90 : ci.q975;

  const x = (v) => ((v - xMin) / (xMax - xMin)) * width;
  const midY = height / 2;

  // Violin path — symmetric mirror
  const violinPath = () => {
    let top = `M ${x(dens[0].x)} ${midY}`;
    dens.forEach(p => { top += ` L ${x(p.x)} ${midY - p.y * (height * 0.42)}`; });
    let bot = '';
    [...dens].reverse().forEach(p => { bot += ` L ${x(p.x)} ${midY + p.y * (height * 0.42)}`; });
    return top + bot + ' Z';
  };

  // Ridge path — flat baseline, top curve only, fill down
  const ridgePath = () => {
    const base = height - 6;
    let d = `M ${x(dens[0].x)} ${base}`;
    dens.forEach(p => { d += ` L ${x(p.x)} ${base - p.y * (height - 12)}`; });
    d += ` L ${x(dens[dens.length - 1].x)} ${base} Z`;
    return d;
  };

  const opacity = dim ? 0.4 : 1;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}
         onClick={onClick}
         style={{ display: 'block', cursor: onClick ? 'pointer' : 'default', opacity }}>
      {/* CI band (under) — subtle horizontal */}
      {(style === 'bar' || style === 'dot') && (
        <>
          {/* 95% rule */}
          <line x1={x(ci.q025)} x2={x(ci.q975)} y1={midY} y2={midY}
                stroke={col} strokeOpacity="0.22" strokeWidth={style === 'bar' ? 14 : 2} strokeLinecap="round" />
          {/* selected CI */}
          <line x1={x(lo)} x2={x(hi)} y1={midY} y2={midY}
                stroke={col} strokeOpacity={style === 'bar' ? 0.55 : 0.85}
                strokeWidth={style === 'bar' ? 14 : 4} strokeLinecap="round" />
          {/* median dot */}
          <circle cx={x(ci.q50)} cy={midY} r={style === 'bar' ? 4 : 5} fill={col} />
          {style === 'dot' && (
            <>
              <circle cx={x(ci.q025)} cy={midY} r={2.5} fill={col} fillOpacity="0.5" />
              <circle cx={x(ci.q975)} cy={midY} r={2.5} fill={col} fillOpacity="0.5" />
            </>
          )}
        </>
      )}

      {style === 'violin' && (
        <>
          <path d={violinPath()} fill={col} fillOpacity="0.18" stroke={col} strokeOpacity="0.6" strokeWidth="1" />
          <line x1={x(lo)} x2={x(hi)} y1={midY} y2={midY}
                stroke={col} strokeOpacity="0.9" strokeWidth="2.5" strokeLinecap="round" />
          <circle cx={x(ci.q50)} cy={midY} r={3.5} fill={col} stroke="#fff" strokeWidth="1.2" />
        </>
      )}

      {style === 'ridge' && (
        <>
          <path d={ridgePath()} fill={col} fillOpacity="0.32" stroke={col} strokeOpacity="0.8" strokeWidth="1.4" />
          <line x1={x(ci.q50)} x2={x(ci.q50)} y1={height - 4} y2={height - 4 - (height - 12)}
                stroke={col} strokeOpacity="0.95" strokeWidth="1.3" strokeDasharray="2 2" />
          <line x1={x(lo)} x2={x(hi)} y1={height - 4} y2={height - 4}
                stroke={col} strokeWidth="2.5" strokeLinecap="round" />
        </>
      )}

      {/* active outline */}
      {active && (
        <rect x="0.5" y="0.5" width={width - 1} height={height - 1}
              fill="none" stroke={col} strokeWidth="1.5" strokeDasharray="3 3" rx="6" />
      )}
    </svg>
  );
}

// — Trajectory chart ————————————————————————————————

function Trajectory({ id, width = 320, height = 140, scrubWeek, onScrub, focusOnly = false }) {
  const series = window.TRAJECTORY[id];
  if (!series) return null;
  const c = window.CANDIDATES.find(x => x.id === id);
  const col = c.color;

  const xMin = 0, xMax = series.length - 1;
  const yMin = 0, yMax = Math.max(...series.map(s => s.q975)) + 2;

  const px = (w) => ((w - xMin) / (xMax - xMin)) * (width - 36) + 30;
  const py = (v) => height - 22 - ((v - yMin) / (yMax - yMin)) * (height - 32);

  const bandPath = (lo, hi) => {
    let d = `M ${px(0)} ${py(series[0][hi])}`;
    series.forEach(s => { d += ` L ${px(s.w)} ${py(s[hi])}`; });
    [...series].reverse().forEach(s => { d += ` L ${px(s.w)} ${py(s[lo])}`; });
    return d + ' Z';
  };
  const linePath = () => {
    let d = `M ${px(0)} ${py(series[0].median)}`;
    series.forEach(s => { d += ` L ${px(s.w)} ${py(s.median)}`; });
    return d;
  };

  // Y tick marks (5 / 10 / 15 ...)
  const ticks = [];
  for (let v = 5; v < yMax; v += 5) ticks.push(v);

  const scrubX = scrubWeek != null ? px(scrubWeek) : null;
  const scrubData = scrubWeek != null ? series[scrubWeek] : null;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}
         onMouseMove={(e) => {
           if (!onScrub) return;
           const r = e.currentTarget.getBoundingClientRect();
           const xp = e.clientX - r.left;
           const w = Math.round(((xp - 30) / (width - 36)) * (xMax - xMin));
           onScrub(Math.max(0, Math.min(xMax, w)));
         }}
         onMouseLeave={() => onScrub && onScrub(null)}
         style={{ display: 'block', cursor: onScrub ? 'col-resize' : 'default' }}>
      {/* gridlines */}
      {ticks.map(v => (
        <g key={v}>
          <line x1={28} x2={width - 6} y1={py(v)} y2={py(v)}
                stroke="var(--line)" strokeWidth="0.5" strokeDasharray="2 3" />
          <text x={24} y={py(v) + 3} fontSize="9" textAnchor="end"
                fill="var(--muted)" fontFamily="var(--font-mono)">{v}</text>
        </g>
      ))}

      {/* 95% band */}
      <path d={bandPath('q025', 'q975')} fill={col} fillOpacity="0.10" />
      {/* 80% band */}
      <path d={bandPath('q10', 'q90')} fill={col} fillOpacity="0.20" />
      {/* median */}
      <path d={linePath()} fill="none" stroke={col} strokeWidth="1.8" strokeLinejoin="round" />

      {/* scrub line */}
      {scrubX != null && (
        <>
          <line x1={scrubX} x2={scrubX} y1={6} y2={height - 22}
                stroke="var(--ink)" strokeWidth="0.7" strokeDasharray="2 2" />
          <circle cx={scrubX} cy={py(scrubData.median)} r="3.5" fill={col} stroke="#fff" strokeWidth="1.2" />
        </>
      )}

      {/* x labels — months back */}
      <text x={30} y={height - 6} fontSize="9" fill="var(--muted)"
            fontFamily="var(--font-mono)">−9 m</text>
      <text x={width - 6} y={height - 6} fontSize="9" textAnchor="end"
            fill="var(--muted)" fontFamily="var(--font-mono)">hoy</text>
    </svg>
  );
}

// — Sparkline (mini trajectory for list rows) —————————————————

function Sparkline({ id, width = 64, height = 22, color }) {
  const series = window.TRAJECTORY[id];
  if (!series) return null;
  const c = window.CANDIDATES.find(x => x.id === id);
  const col = color || c.color;
  const yMin = Math.min(...series.map(s => s.median)) - 1;
  const yMax = Math.max(...series.map(s => s.median)) + 1;
  const px = (w) => (w / (series.length - 1)) * width;
  const py = (v) => height - ((v - yMin) / (yMax - yMin)) * height;
  let d = `M ${px(0)} ${py(series[0].median)}`;
  series.forEach(s => { d += ` L ${px(s.w)} ${py(s.median)}`; });
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      <path d={d} fill="none" stroke={col} strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={px(series.length - 1)} cy={py(series[series.length - 1].median)} r="2" fill={col} />
    </svg>
  );
}

// — Win-probability bar ——————————————————————————————

function WinBar({ p, color, label, width = 90, height = 6 }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{
        width, height, borderRadius: height,
        background: 'color-mix(in oklch, var(--line) 70%, transparent)',
        position: 'relative', overflow: 'hidden',
      }}>
        <div style={{
          width: `${Math.max(2, p * 100)}%`, height: '100%',
          background: color, borderRadius: height,
        }} />
      </div>
      {label !== false && (
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 11,
          fontVariantNumeric: 'tabular-nums', color: 'var(--ink)',
          minWidth: 32, textAlign: 'right',
        }}>{Math.round(p * 100)}%</span>
      )}
    </div>
  );
}

// — Runoff matrix ————————————————————————————————

function RunoffMatrix({ onCellTap, selectedPair, ciLevel = 80, width = 340 }) {
  const ranked = window.CANDIDATES.filter(c => !c.isOther).slice(0, 6);
  // Cell color: amount above/below 50%, on a warm diverging scale.
  const cellBg = (p) => {
    if (p == null) return 'var(--line)';
    const d = (p - 50) / 50; // -1..1
    if (d >= 0) {
      // Toward warm green
      return `color-mix(in oklch, oklch(0.78 0.07 145) ${Math.abs(d) * 100}%, var(--paper))`;
    }
    return `color-mix(in oklch, oklch(0.78 0.09 35) ${Math.abs(d) * 100}%, var(--paper))`;
  };

  const N = ranked.length;
  const gapTotal = N - 1; // 1px gap between cells
  const cellSize = Math.floor((width - 64 - gapTotal) / N);
  const headerSize = 64;
  const gridWidth = N * cellSize + gapTotal;

  return (
    <div style={{ width, fontFamily: 'var(--font-body)' }}>
      {/* Top headers (columns) — adversaries */}
      <div style={{ display: 'flex', alignItems: 'flex-end', height: headerSize, gap: 1, paddingLeft: 64 }}>
        {ranked.map(c => (
          <div key={c.id} style={{
            width: cellSize, height: headerSize,
            display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
            paddingBottom: 4,
          }}>
            <div style={{
              transform: 'rotate(-55deg)', transformOrigin: 'left bottom',
              whiteSpace: 'nowrap', fontSize: 10, fontWeight: 600,
              color: 'var(--ink)', letterSpacing: '0.02em',
            }}>
              <span style={{
                display: 'inline-block', width: 5, height: 5, borderRadius: 5,
                background: c.color, marginRight: 4, transform: 'translateY(-0.5px)',
              }} />
              {c.last}
            </div>
          </div>
        ))}
      </div>

      {/* Rows */}
      {ranked.map(r => (
        <div key={r.id} style={{ display: 'flex', alignItems: 'center', gap: 1, marginBottom: 1 }}>
          {/* Row label */}
          <div style={{
            width: 64, fontSize: 10.5, fontWeight: 600, color: 'var(--ink)',
            display: 'flex', alignItems: 'center', gap: 4, paddingRight: 4,
            justifyContent: 'flex-end', whiteSpace: 'nowrap',
          }}>
            {r.last}
            <span style={{
              width: 5, height: 5, borderRadius: 5, background: r.color,
            }} />
          </div>
          {ranked.map(c => {
            if (r.id === c.id) {
              return (
                <div key={c.id} style={{
                  width: cellSize, height: cellSize,
                  background: 'color-mix(in oklch, var(--ink) 8%, transparent)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 14, color: 'var(--muted)',
                }}>·</div>
              );
            }
            const cell = window.RUNOFF_PAIRS[r.id]?.[c.id];
            const selected = selectedPair && selectedPair[0] === r.id && selectedPair[1] === c.id;
            return (
              <button key={c.id} onClick={() => onCellTap && onCellTap(r, c, cell)}
                      style={{
                        width: cellSize, height: cellSize, padding: 0, border: 'none',
                        background: cellBg(cell?.prob),
                        outline: selected ? '2px solid var(--ink)' : 'none',
                        outlineOffset: -2,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600,
                        color: 'var(--ink)', fontVariantNumeric: 'tabular-nums',
                        cursor: 'pointer',
                      }}>
                {cell?.prob}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

// — Pollster house-effects forest plot ————————————————————

function PollsterForest({ width = 280, height = null }) {
  const ps = window.POLLSTERS;
  const xMin = -6, xMax = +6;
  const rowH = 26;
  const h = height || (ps.length * rowH + 32);
  const lx = 112;
  const px = (v) => lx + ((v - xMin) / (xMax - xMin)) * (width - lx - 12);
  return (
    <svg width={width} height={h} viewBox={`0 0 ${width} ${h}`} style={{ display: 'block' }}>
      {/* zero line */}
      <line x1={px(0)} x2={px(0)} y1={6} y2={h - 18}
            stroke="var(--ink)" strokeWidth="0.6" />
      {/* tick labels */}
      {[-4, -2, 0, 2, 4].map(v => (
        <g key={v}>
          <line x1={px(v)} x2={px(v)} y1={h - 18} y2={h - 14}
                stroke="var(--muted)" strokeWidth="0.5" />
          <text x={px(v)} y={h - 4} textAnchor="middle"
                fontSize="9" fill="var(--muted)" fontFamily="var(--font-mono)">
            {v > 0 ? '+' + v : v}
          </text>
        </g>
      ))}
      {ps.map((p, i) => {
        const y = 12 + i * rowH;
        const lo = p.biasMean - p.biasSd, hi = p.biasMean + p.biasSd;
        return (
          <g key={p.id}>
            <text x={lx - 6} y={y + 4} textAnchor="end" fontSize="10.5"
                  fill="var(--ink)" fontFamily="var(--font-body)" fontWeight="500">{p.name}</text>
            <line x1={px(lo)} x2={px(hi)} y1={y} y2={y}
                  stroke="var(--ink)" strokeOpacity="0.65" strokeWidth="2" strokeLinecap="round" />
            <circle cx={px(p.biasMean)} cy={y} r="3.5" fill="var(--accent)" />
          </g>
        );
      })}
    </svg>
  );
}

Object.assign(window, {
  Posterior, Trajectory, Sparkline, WinBar, RunoffMatrix, PollsterForest,
});
