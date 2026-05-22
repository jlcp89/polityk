// screens.jsx — main screens for polityc

// — HOME / FORECAST SCREEN ————————————————————————————

function HomeScreen({ chartStyle, ciLevel, setCiLevel, density, freshness,
                       round, setRound, onCandidate, onRunoff, onMethod,
                       scrubWeek, setScrubWeek }) {
  const candidates = window.CANDIDATES;
  const ranked = candidates.filter(c => !c.isOther);

  const xMax = round === 1 ? 36 : 70;
  const xMin = 0;
  const xTicks = round === 1 ? [0, 10, 20, 30] : [0, 25, 50, 75];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', paddingBottom: 24 }}>
      <FreshnessBanner state={freshness} />

      {/* Eyebrow + headline */}
      <div style={{ padding: '16px 18px 8px' }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginBottom: 6,
        }}>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 10,
            color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
          }}>Elecciones 2027 · 396 días</div>
          <Chip tone="ghost" size="sm">{window.CALIBRATION.modelVersion}</Chip>
        </div>
        <h1 style={{
          margin: 0, fontFamily: 'var(--font-display)',
          fontWeight: 500, fontSize: 30, lineHeight: 1.0,
          letterSpacing: '-0.015em', color: 'var(--ink)',
          textWrap: 'pretty',
        }}>
          Pronóstico <em style={{ fontStyle: 'italic', color: 'var(--accent)' }}>presidencial</em>
        </h1>
        <div style={{
          marginTop: 8, fontSize: 12.5, color: 'var(--ink-soft)', lineHeight: 1.45,
          textWrap: 'pretty',
        }}>
          Distribución posterior por candidato — agregador jerárquico bayesiano
          calibrado contra 2019 y 2023.
        </div>
      </div>

      {/* Round selector */}
      <div style={{ padding: '4px 18px 10px' }}>
        <SegmentedRound value={round} onChange={setRound} />
      </div>

      {/* Density hero */}
      <div style={{
        margin: '0 14px 0', padding: '14px 14px 8px',
        background: 'var(--card)', borderRadius: 14,
        border: '0.5px solid var(--line)',
        boxShadow: '0 1px 0 color-mix(in oklch, var(--ink) 4%, transparent)',
      }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
          marginBottom: 4,
        }}>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 10,
            color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
          }}>
            {round === 1 ? 'Voto válido · 1ra vuelta' : 'Voto válido · 2da vuelta (si pasa)'}
          </div>
          <CILevelToggle value={ciLevel} onChange={setCiLevel} />
        </div>

        {/* Density rows */}
        <div style={{ marginTop: 8 }}>
          {ranked.map((c, i) => (
            <DensityRow key={c.id} c={c}
                         chartStyle={chartStyle}
                         ciLevel={ciLevel}
                         xMin={xMin} xMax={xMax}
                         round={round}
                         density={density}
                         onTap={() => onCandidate(c.id)} />
          ))}
        </div>

        {/* X axis */}
        <div style={{
          position: 'relative', height: 18, marginLeft: 90, marginRight: 4,
          marginTop: 4, borderTop: '0.5px solid var(--line)',
        }}>
          {xTicks.map(t => (
            <div key={t} style={{
              position: 'absolute',
              left: `calc(${(t - xMin) / (xMax - xMin) * 100}% - 8px)`,
              top: 4, fontFamily: 'var(--font-mono)', fontSize: 9.5,
              color: 'var(--muted)',
            }}>{t}%</div>
          ))}
        </div>

        {/* Otros aggregated */}
        <div style={{
          marginTop: 8, paddingTop: 10, borderTop: '0.5px dashed var(--line)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          fontSize: 11.5, color: 'var(--muted)',
        }}>
          <span>Otros + indecisos + nulo · ~16.2%</span>
          <Chip tone="ghost" size="sm">agregado</Chip>
        </div>
      </div>

      {/* Time scrubber */}
      <div style={{ padding: '16px 18px 0' }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
          marginBottom: 6,
        }}>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 10,
            color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
          }}>Evolución temporal</div>
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--ink-soft)',
            fontVariantNumeric: 'tabular-nums',
          }}>
            {scrubWeek != null
              ? `sem ${scrubWeek + 1}/40 · ${weekLabel(scrubWeek)}`
              : 'arrastre para retroceder'}
          </span>
        </div>
        <TrajectoryStrip scrubWeek={scrubWeek} setScrubWeek={setScrubWeek}
                          ciLevel={ciLevel} />
      </div>

      {/* Quick links */}
      <div style={{ padding: '18px 14px 0', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <CardLink eyebrow="Segunda vuelta"
                   title="Matriz de enfrentamientos"
                   sub={`${(window.CANDIDATES[0].winR1 * 100).toFixed(0)}% prob. de pase para Torres · 6×6 escenarios`}
                   onClick={onRunoff} />
        <CardLink eyebrow="Metodología"
                   title="Cómo se construye este pronóstico"
                   sub="Linzer/Kremp · fundamentos · sentimiento opcional · gate de calibración"
                   onClick={onMethod} />
      </div>

      {/* Footer-ish */}
      <div style={{
        marginTop: 18, padding: '10px 18px 4px',
        fontFamily: 'var(--font-mono)', fontSize: 9.5,
        color: 'var(--muted)', lineHeight: 1.5,
      }}>
        Última corrida {window.CALIBRATION.runId}<br />
        Generado {window.fmtDate(window.CALIBRATION.generatedAt)}<br />
        Próxima publicación {window.fmtDate(window.CALIBRATION.nextRun, { time: false })}
      </div>
    </div>
  );
}

function weekLabel(w) {
  // Map week 0 → ~9 months ago, week 39 → now
  const days = (39 - w) * 7;
  const d = new Date(2026, 4, 21 - days);
  return d.toLocaleDateString('es-GT', { day: 'numeric', month: 'short' });
}

// — Density row (one candidate) ————————————————————————

function DensityRow({ c, chartStyle, ciLevel, xMin, xMax, round, density, onTap }) {
  const ci = window.intervals(c);
  const winProb = round === 1 ? c.winR1 : c.winPres;
  // Adjust mean/sd for round 2: rough conditional re-estimate
  const cR2 = round === 2 ? { ...c, mean: c.mean * 2.2 + (c.id === 'torres' ? -2 : c.id === 'herrera' ? 4 : 0), sd: c.sd * 1.6 } : c;

  const compactH = density === 'compact' ? 38 : density === 'comfy' ? 64 : 50;

  return (
    <button onClick={onTap} style={{
      display: 'flex', alignItems: 'center', gap: 6,
      width: '100%', padding: '4px 0', margin: 0,
      border: 'none', background: 'transparent', textAlign: 'left', cursor: 'pointer',
      borderBottom: '0.5px dashed color-mix(in oklch, var(--line) 60%, transparent)',
    }}>
      {/* Label column */}
      <div style={{ width: 84, flexShrink: 0 }}>
        <div style={{
          fontFamily: 'var(--font-display)', fontSize: 14, fontWeight: 500,
          color: 'var(--ink)', lineHeight: 1.05,
          display: 'flex', alignItems: 'center', gap: 4,
        }}>
          <span style={{
            width: 6, height: 6, borderRadius: 6, background: c.color, flexShrink: 0,
          }} />
          {c.last}
        </div>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)',
          letterSpacing: '0.04em', marginTop: 1, paddingLeft: 10,
        }}>{c.party}</div>
      </div>

      {/* Density */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <window.Posterior c={cR2} style={chartStyle} ciLevel={ciLevel}
                           xMin={xMin} xMax={xMax}
                           width={170} height={compactH} />
      </div>

      {/* Median + win prob */}
      <div style={{ width: 66, flexShrink: 0, textAlign: 'right', paddingRight: 6 }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 600,
          color: 'var(--ink)', fontVariantNumeric: 'tabular-nums',
        }}>{round === 2 ? cR2.mean.toFixed(0) : c.mean.toFixed(1)}%</div>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)',
          fontVariantNumeric: 'tabular-nums', marginTop: 1,
        }}>
          {ciLevel === 80
            ? `${ci.q10.toFixed(0)}–${ci.q90.toFixed(0)}`
            : `${ci.q025.toFixed(0)}–${ci.q975.toFixed(0)}`}
        </div>
        <div style={{ marginTop: 3 }}>
          <window.WinBar p={winProb} color={c.color} width={56} height={4} label={false} />
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--ink-soft)',
            fontVariantNumeric: 'tabular-nums', textAlign: 'right', marginTop: 1,
          }}>{Math.round(winProb * 100)}% {round === 1 ? 'pase' : 'pres.'}</div>
        </div>
      </div>
    </button>
  );
}

// — Segmented controls ——————————————————————————————

function SegmentedRound({ value, onChange }) {
  const opts = [
    { v: 1, label: 'Primera vuelta' },
    { v: 2, label: 'Segunda vuelta' },
  ];
  return (
    <div style={{
      display: 'flex', padding: 2,
      background: 'color-mix(in oklch, var(--ink) 6%, transparent)',
      borderRadius: 10, position: 'relative',
    }}>
      <div style={{
        position: 'absolute', top: 2, bottom: 2,
        left: value === 1 ? 2 : 'calc(50% + 0px)',
        width: 'calc(50% - 2px)',
        background: 'var(--paper)',
        borderRadius: 8,
        boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
        transition: 'left .18s cubic-bezier(.3,.7,.4,1)',
      }} />
      {opts.map(o => (
        <button key={o.v} onClick={() => onChange(o.v)}
                style={{
                  flex: 1, padding: '8px 0', border: 'none',
                  background: 'transparent', position: 'relative', zIndex: 1,
                  fontFamily: 'var(--font-body)', fontSize: 12, fontWeight: value === o.v ? 600 : 500,
                  color: value === o.v ? 'var(--ink)' : 'var(--muted)',
                  cursor: 'pointer',
                }}>{o.label}</button>
      ))}
    </div>
  );
}

function CILevelToggle({ value, onChange }) {
  return (
    <div style={{
      display: 'inline-flex', borderRadius: 7,
      border: '0.5px solid var(--line)',
      background: 'var(--paper)', overflow: 'hidden',
    }}>
      {[80, 95].map(v => (
        <button key={v} onClick={() => onChange(v)}
                style={{
                  padding: '3px 8px', border: 'none',
                  background: value === v ? 'var(--ink)' : 'transparent',
                  color: value === v ? 'var(--paper)' : 'var(--ink-soft)',
                  fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600,
                  cursor: 'pointer',
                }}>{v}%</button>
      ))}
    </div>
  );
}

// — Mini trajectory strip for scrubbing ——————————————————

function TrajectoryStrip({ scrubWeek, setScrubWeek, ciLevel }) {
  const W = 340, H = 110;
  const candidates = window.CANDIDATES.filter(c => !c.isOther);
  const all = candidates.flatMap(c => window.TRAJECTORY[c.id]);
  const yMax = Math.max(...all.map(s => s.median)) + 4;
  const xMax = 39;
  const px = (w) => 8 + (w / xMax) * (W - 16);
  const py = (v) => H - 18 - (v / yMax) * (H - 28);

  return (
    <div style={{
      background: 'var(--card)', borderRadius: 14,
      border: '0.5px solid var(--line)', padding: '12px 6px 6px',
      position: 'relative',
    }}
         onMouseMove={(e) => {
           const r = e.currentTarget.getBoundingClientRect();
           const xp = e.clientX - r.left - 6;
           const w = Math.round((xp / (W - 16)) * xMax);
           setScrubWeek(Math.max(0, Math.min(xMax, w)));
         }}
         onMouseLeave={() => setScrubWeek(null)}
         onTouchMove={(e) => {
           const r = e.currentTarget.getBoundingClientRect();
           const t = e.touches[0];
           const xp = t.clientX - r.left - 6;
           const w = Math.round((xp / (W - 16)) * xMax);
           setScrubWeek(Math.max(0, Math.min(xMax, w)));
         }}>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
        {/* gridlines */}
        {[10, 20].map(v => (
          <line key={v} x1={8} x2={W - 8} y1={py(v)} y2={py(v)}
                stroke="var(--line)" strokeWidth="0.5" strokeDasharray="2 3" />
        ))}
        {/* Y labels */}
        {[10, 20].map(v => (
          <text key={v} x={W - 10} y={py(v) - 2} textAnchor="end"
                fontSize="9" fill="var(--muted)" fontFamily="var(--font-mono)">{v}%</text>
        ))}

        {/* All candidate lines */}
        {candidates.map(c => {
          const s = window.TRAJECTORY[c.id];
          let d = `M ${px(0)} ${py(s[0].median)}`;
          s.forEach(pt => { d += ` L ${px(pt.w)} ${py(pt.median)}`; });
          return (
            <path key={c.id} d={d} fill="none" stroke={c.color} strokeWidth="1.4"
                  strokeLinejoin="round" strokeLinecap="round" />
          );
        })}

        {/* Scrub line */}
        {scrubWeek != null && (
          <>
            <line x1={px(scrubWeek)} x2={px(scrubWeek)} y1={4} y2={H - 18}
                  stroke="var(--ink)" strokeWidth="0.8" strokeDasharray="2 2" />
            {candidates.map(c => {
              const s = window.TRAJECTORY[c.id][scrubWeek];
              return (
                <circle key={c.id} cx={px(scrubWeek)} cy={py(s.median)} r="3"
                        fill={c.color} stroke="var(--paper)" strokeWidth="1.2" />
              );
            })}
          </>
        )}
      </svg>

      {/* Bottom labels */}
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        padding: '0 8px', marginTop: -4,
      }}>
        {['ago 2025', 'nov 2025', 'feb 2026', 'may 2026'].map((l, i) => (
          <span key={i} style={{
            fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)',
          }}>{l}</span>
        ))}
      </div>

      {/* Scrub readout */}
      {scrubWeek != null && (
        <div style={{
          position: 'absolute', top: 8, left: 12,
          fontFamily: 'var(--font-mono)', fontSize: 9.5,
          background: 'var(--ink)', color: 'var(--paper)',
          padding: '3px 6px', borderRadius: 4,
          pointerEvents: 'none',
        }}>
          {candidates.slice(0, 3).map(c => (
            <div key={c.id} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ width: 5, height: 5, borderRadius: 5, background: c.color }} />
              <span style={{ minWidth: 56 }}>{c.last}</span>
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                {window.TRAJECTORY[c.id][scrubWeek].median.toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// — CardLink for navigation rows ——————————————————————

function CardLink({ eyebrow, title, sub, onClick }) {
  return (
    <button onClick={onClick} style={{
      display: 'flex', flexDirection: 'column', gap: 4,
      padding: '12px 14px', textAlign: 'left',
      background: 'var(--card)', border: '0.5px solid var(--line)',
      borderRadius: 12, cursor: 'pointer',
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
        }}>{eyebrow}</div>
        <span style={{ color: 'var(--muted)', fontSize: 14 }}>›</span>
      </div>
      <div style={{
        fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 500,
        color: 'var(--ink)', lineHeight: 1.15,
      }}>{title}</div>
      {sub && (
        <div style={{ fontSize: 11.5, color: 'var(--ink-soft)', lineHeight: 1.4 }}>{sub}</div>
      )}
    </button>
  );
}

Object.assign(window, {
  HomeScreen, DensityRow, SegmentedRound, CILevelToggle,
  TrajectoryStrip, CardLink, weekLabel,
});
