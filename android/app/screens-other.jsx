// screens-other.jsx — candidate detail, runoff, methodology, status, interventions, blackout

// — CANDIDATE DETAIL ——————————————————————————————

function CandidateDetail({ candidateId, onClose, ciLevel, chartStyle }) {
  const c = window.CANDIDATES.find(x => x.id === candidateId);
  if (!c) return null;
  const ci = window.intervals(c);
  const polls = window.POLLS[c.id] || [];

  return (
    <window.BottomSheet open={true} onClose={onClose} maxHeight={0.92}>
      {/* Header */}
      <div style={{ padding: '4px 18px 14px', borderBottom: '0.5px solid var(--line)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            width: 10, height: 10, borderRadius: 10, background: c.color, flexShrink: 0,
          }} />
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 10,
            color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
          }}>{c.partyFull}</div>
        </div>
        <h2 style={{
          margin: '4px 0 0', fontFamily: 'var(--font-display)',
          fontWeight: 500, fontSize: 26, lineHeight: 1.0,
          letterSpacing: '-0.01em', color: 'var(--ink)',
        }}>
          {c.first} {c.last}
        </h2>
        <div style={{ marginTop: 6, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <window.Chip tone="ghost" size="sm">{c.runs === 1 ? 'Primer intento' : `${c.runs}.ª candidatura`}</window.Chip>
          {c.incumbentParty && <window.Chip tone="accent" size="sm">Partido oficialista</window.Chip>}
          {c.notes && c.notes.includes('Elegibilidad') && (
            <window.Chip tone="warn" size="sm">Inscripción pendiente</window.Chip>
          )}
        </div>
      </div>

      {/* Stats grid */}
      <div style={{
        padding: '14px 18px', display: 'grid', gap: 14,
        gridTemplateColumns: '1fr 1fr 1fr',
      }}>
        <window.Stat label="Mediana 1ra" value={`${c.mean.toFixed(1)}%`}
                      sub={`IC ${ciLevel}%: ${(ciLevel === 80 ? ci.q10 : ci.q025).toFixed(1)}–${(ciLevel === 80 ? ci.q90 : ci.q975).toFixed(1)}`}
                      color={c.color} />
        <window.Stat label="Pase 2da" value={`${Math.round(c.winR1 * 100)}%`}
                      sub="prob. de qualificar" />
        <window.Stat label="Presidencia" value={`${Math.round(c.winPres * 100)}%`}
                      sub="prob. final" />
      </div>

      {/* Posterior density (large) */}
      <div style={{ padding: '0 18px 8px' }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
          marginBottom: 6,
        }}>Posterior 1ra vuelta</div>
        <div style={{
          background: 'var(--card)', borderRadius: 12,
          border: '0.5px solid var(--line)', padding: '14px 14px 8px',
        }}>
          <window.Posterior c={c} style="violin" ciLevel={ciLevel}
                             xMin={0} xMax={36} width={340} height={90} />
          <div style={{
            display: 'flex', justifyContent: 'space-between', marginTop: 2,
            fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)',
          }}>
            <span>0%</span><span>10%</span><span>20%</span><span>30%</span>
          </div>
          <div style={{
            display: 'flex', gap: 12, marginTop: 10, paddingTop: 8,
            borderTop: '0.5px solid var(--line)',
            fontFamily: 'var(--font-mono)', fontSize: 10.5,
            fontVariantNumeric: 'tabular-nums', color: 'var(--ink-soft)',
          }}>
            <span><span style={{ color: 'var(--muted)' }}>q10</span> {ci.q10.toFixed(1)}</span>
            <span><span style={{ color: 'var(--muted)' }}>q25</span> {window.quantile(c.mean, c.sd, 0.25).toFixed(1)}</span>
            <span><b>q50 {ci.q50.toFixed(1)}</b></span>
            <span><span style={{ color: 'var(--muted)' }}>q75</span> {window.quantile(c.mean, c.sd, 0.75).toFixed(1)}</span>
            <span><span style={{ color: 'var(--muted)' }}>q90</span> {ci.q90.toFixed(1)}</span>
          </div>
        </div>
      </div>

      {/* Trajectory */}
      <div style={{ padding: '8px 18px' }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
          marginBottom: 6,
        }}>Trayectoria · últimos 9 meses</div>
        <div style={{
          background: 'var(--card)', borderRadius: 12,
          border: '0.5px solid var(--line)', padding: '12px 6px 4px',
        }}>
          <window.Trajectory id={c.id} width={340} height={140} />
        </div>
        <div style={{
          display: 'flex', gap: 14, marginTop: 6,
          fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)',
        }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 12, height: 6, background: c.color, opacity: 0.4 }} />
            IC 80%
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 12, height: 6, background: c.color, opacity: 0.2 }} />
            IC 95%
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 12, height: 2, background: c.color }} />
            mediana
          </span>
        </div>
      </div>

      {/* Pollster breakdown */}
      <div style={{ padding: '12px 18px 4px' }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
          marginBottom: 6,
        }}>Lecturas recientes por casa encuestadora</div>
        <div style={{
          background: 'var(--card)', borderRadius: 12,
          border: '0.5px solid var(--line)', overflow: 'hidden',
        }}>
          {polls.slice(0, 8).map((poll, i) => {
            const p = window.POLLSTERS.find(x => x.id === poll.p);
            return (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', padding: '8px 12px',
                gap: 10,
                borderBottom: i < 7 ? '0.5px solid var(--line)' : 'none',
              }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 11.5, fontWeight: 500 }}>{p.name}</div>
                  <div style={{
                    fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)',
                  }}>
                    hace {poll.w} sem · n={poll.n} · MoE ±{poll.moe}
                  </div>
                </div>
                <div style={{
                  fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600,
                  fontVariantNumeric: 'tabular-nums',
                }}>{poll.share}%</div>
                <PollDot share={poll.share} mean={c.mean} sd={c.sd} color={c.color} />
              </div>
            );
          })}
        </div>
      </div>

      {/* Notes */}
      {c.notes && (
        <div style={{
          padding: '12px 18px 18px',
        }}>
          <div style={{
            fontSize: 11.5, color: 'var(--ink-soft)', lineHeight: 1.5,
            fontStyle: 'italic',
            borderLeft: '2px solid var(--accent)',
            paddingLeft: 10,
          }}>
            {c.notes}
          </div>
        </div>
      )}
    </window.BottomSheet>
  );
}

function PollDot({ share, mean, sd, color }) {
  // Show how far this poll is from the posterior mean — small visual
  const z = (share - mean) / sd;
  const off = Math.max(-2.5, Math.min(2.5, z));
  return (
    <div style={{ width: 50, height: 16, position: 'relative' }}>
      <div style={{
        position: 'absolute', top: 7, left: 0, right: 0,
        height: 2, background: 'var(--line)', borderRadius: 2,
      }} />
      <div style={{
        position: 'absolute', top: 7, left: '50%', width: 2, height: 8, marginTop: -3,
        background: 'var(--muted)', opacity: 0.5,
      }} />
      <div style={{
        position: 'absolute', top: 5, width: 6, height: 6, borderRadius: 6,
        left: `calc(50% + ${off * 9}px - 3px)`,
        background: color, boxShadow: '0 0 0 1px var(--paper)',
      }} />
    </div>
  );
}

// — RUNOFF SCREEN ——————————————————————————————

function RunoffScreen({ ciLevel, freshness, onCandidate }) {
  const [selectedPair, setSelectedPair] = React.useState(null);
  const handleCell = (r, c, cell) => {
    setSelectedPair([r.id, c.id]);
  };
  return (
    <div style={{ paddingBottom: 24 }}>
      <FreshnessBanner state={freshness} />
      <div style={{ padding: '16px 18px 8px' }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
          marginBottom: 4,
        }}>Segunda vuelta</div>
        <h1 style={{
          margin: 0, fontFamily: 'var(--font-display)',
          fontWeight: 500, fontSize: 28, lineHeight: 1.0,
          letterSpacing: '-0.01em', color: 'var(--ink)',
          textWrap: 'pretty',
        }}>
          ¿Quién <em style={{ fontStyle: 'italic', color: 'var(--accent)' }}>gana</em> si pasan dos?
        </h1>
        <div style={{
          marginTop: 8, fontSize: 12, color: 'var(--ink-soft)', lineHeight: 1.5,
        }}>
          Probabilidad <b>condicional</b> de que la fila venza a la columna,
          dado que ambos pasen a segunda vuelta. Toque una celda para detalle.
        </div>
      </div>

      <div style={{ padding: '6px 14px' }}>
        <div style={{
          background: 'var(--card)', borderRadius: 14,
          border: '0.5px solid var(--line)', padding: '14px 12px',
          overflowX: 'auto',
        }}>
          <window.RunoffMatrix onCellTap={handleCell} selectedPair={selectedPair}
                                ciLevel={ciLevel} width={336} />
        </div>
      </div>

      {/* Legend */}
      <div style={{ padding: '0 18px', marginTop: 8 }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)',
        }}>
          <span>0%</span>
          <div style={{
            flex: 1, height: 8, borderRadius: 8,
            background: 'linear-gradient(to right, oklch(0.78 0.09 35), var(--paper), oklch(0.78 0.07 145))',
          }} />
          <span>100%</span>
        </div>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)',
          display: 'flex', justifyContent: 'space-between', marginTop: 2,
        }}>
          <span>pierde</span>
          <span>50% — empate</span>
          <span>gana</span>
        </div>
      </div>

      {/* Detail card */}
      {selectedPair && (
        <PairDetail pair={selectedPair} onClose={() => setSelectedPair(null)}
                     onCandidate={onCandidate} />
      )}

      {/* Most likely matchups */}
      <div style={{ padding: '18px 18px 0' }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
          marginBottom: 6,
        }}>Enfrentamientos más probables</div>
        {[
          ['torres', 'rios', 18],
          ['torres', 'herrera', 14],
          ['torres', 'conde', 9],
          ['rios', 'herrera', 7],
        ].map(([a, b, jp], i) => {
          const ca = window.CANDIDATES.find(c => c.id === a);
          const cb = window.CANDIDATES.find(c => c.id === b);
          const cell = window.RUNOFF_PAIRS[a]?.[b];
          return (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '8px 0',
              borderBottom: '0.5px dashed var(--line)',
            }}>
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)',
                width: 36,
              }}>{jp}%</span>
              <span style={{
                fontFamily: 'var(--font-display)', fontSize: 14, fontWeight: 500,
                color: 'var(--ink)', display: 'flex', alignItems: 'center', gap: 5,
              }}>
                <span style={{ width: 6, height: 6, borderRadius: 6, background: ca.color }} />
                {ca.last}
              </span>
              <span style={{ color: 'var(--muted)', fontSize: 10 }}>vs</span>
              <span style={{
                fontFamily: 'var(--font-display)', fontSize: 14, fontWeight: 500,
                color: 'var(--ink)', display: 'flex', alignItems: 'center', gap: 5,
              }}>
                <span style={{ width: 6, height: 6, borderRadius: 6, background: cb.color }} />
                {cb.last}
              </span>
              <span style={{ flex: 1 }} />
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600,
                fontVariantNumeric: 'tabular-nums', color: 'var(--ink)',
                whiteSpace: 'nowrap', flexShrink: 0,
              }}>{cell.prob} / {100 - cell.prob}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PairDetail({ pair, onClose, onCandidate }) {
  const [aId, bId] = pair;
  const a = window.CANDIDATES.find(c => c.id === aId);
  const b = window.CANDIDATES.find(c => c.id === bId);
  const ab = window.RUNOFF_PAIRS[aId]?.[bId];
  const ba = window.RUNOFF_PAIRS[bId]?.[aId];
  return (
    <div style={{
      margin: '14px 14px 0',
      padding: '14px',
      background: 'var(--card)',
      border: '0.5px solid var(--line)',
      borderRadius: 14,
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
        marginBottom: 8,
      }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
        }}>Escenario seleccionado</div>
        <button onClick={onClose} style={{
          border: 'none', background: 'transparent', fontSize: 14, color: 'var(--muted)',
          cursor: 'pointer', padding: 2, lineHeight: 1,
        }}>×</button>
      </div>

      {/* Title */}
      <div style={{
        fontFamily: 'var(--font-display)', fontSize: 18, lineHeight: 1.15,
        marginBottom: 12,
      }}>
        <span style={{ color: a.color, fontWeight: 600 }}>{a.last}</span>
        <span style={{ color: 'var(--muted)', margin: '0 6px' }}>vs</span>
        <span style={{ color: b.color, fontWeight: 600 }}>{b.last}</span>
      </div>

      {/* Bar */}
      <div style={{
        height: 30, display: 'flex', borderRadius: 8, overflow: 'hidden',
        border: '0.5px solid var(--line)',
      }}>
        <div style={{
          width: `${ab.prob}%`, background: a.color,
          color: 'var(--paper)', display: 'flex', alignItems: 'center',
          paddingLeft: 8,
          fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600,
        }}>{ab.prob}%</div>
        <div style={{
          width: `${ba.prob}%`, background: b.color,
          color: 'var(--paper)', display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
          paddingRight: 8,
          fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600,
        }}>{ba.prob}%</div>
      </div>

      {/* Joint */}
      <div style={{
        marginTop: 10, padding: '10px 12px',
        background: 'color-mix(in oklch, var(--ink) 4%, transparent)',
        borderRadius: 8, fontSize: 11.5, color: 'var(--ink-soft)', lineHeight: 1.4,
      }}>
        Probabilidad conjunta de que ambos lleguen a 2da vuelta:{' '}
        <b style={{
          fontFamily: 'var(--font-mono)', fontSize: 12,
          fontVariantNumeric: 'tabular-nums', color: 'var(--ink)',
        }}>{ab.joint}%</b>.
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
        <button onClick={() => onCandidate(a.id)} style={mini(a.color)}>Ver {a.last} →</button>
        <button onClick={() => onCandidate(b.id)} style={mini(b.color)}>Ver {b.last} →</button>
      </div>
    </div>
  );
}

function mini(c) {
  return {
    flex: 1, padding: '8px 10px',
    background: 'transparent', border: `0.5px solid ${c}`, color: c,
    borderRadius: 8, cursor: 'pointer',
    fontFamily: 'var(--font-body)', fontSize: 11.5, fontWeight: 500,
  };
}

// — METHODOLOGY SCREEN ——————————————————————————————

function MethodologyScreen({ freshness, onIntervention, simulateIntervention }) {
  return (
    <div style={{ paddingBottom: 24 }}>
      <window.FreshnessBanner state={freshness} />

      <div style={{ padding: '16px 18px 4px' }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
          marginBottom: 4,
        }}>Metodología · v{window.CALIBRATION.modelVersion}</div>
        <h1 style={{
          margin: 0, fontFamily: 'var(--font-display)',
          fontWeight: 500, fontSize: 28, lineHeight: 1.0,
          letterSpacing: '-0.01em', color: 'var(--ink)',
          textWrap: 'pretty',
        }}>
          ¿Cómo se construye <em style={{ fontStyle: 'italic', color: 'var(--accent)' }}>esto</em>?
        </h1>
        <p style={{
          margin: '10px 0 0', fontSize: 12.5, color: 'var(--ink-soft)',
          lineHeight: 1.55, textWrap: 'pretty',
        }}>
          Combinamos un agregador estatal-espacial de encuestas
          <em> (Linzer/Kremp)</em> con una regresión de fundamentos
          (incumbencia, PIB, inflación, remesas, seguridad). El combinador
          presidencial simula 10 mil primeras vueltas y, condicionalmente,
          segundas vueltas con una matriz de transferencia aprendida sobre
          2007–2023.
        </p>
      </div>

      {/* Pipeline diagram */}
      <div style={{ padding: '14px 14px 0' }}>
        <div style={{
          background: 'var(--card)', border: '0.5px solid var(--line)',
          borderRadius: 14, padding: '14px',
        }}>
          <PipelineDiagram />
        </div>
      </div>

      {/* Pollster house-effects */}
      <div style={{ padding: '14px 14px 0' }}>
        <div style={{
          background: 'var(--card)', border: '0.5px solid var(--line)',
          borderRadius: 14, padding: '14px 14px 6px',
        }}>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 10,
            color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
            marginBottom: 4,
          }}>Sesgo histórico por casa encuestadora</div>
          <div style={{ fontSize: 11.5, color: 'var(--ink-soft)', lineHeight: 1.4, marginBottom: 8 }}>
            Estimado contra ciclos 2007–2023. Positivo = sobreestima al puntero. ProDatos
            falló por +12.6 pp con Arévalo en 2023.
          </div>
          <window.PollsterForest width={340} />
        </div>
      </div>

      {/* Calibration */}
      <div style={{ padding: '14px 14px 0' }}>
        <div style={{
          background: 'var(--card)', border: '0.5px solid var(--line)',
          borderRadius: 14, padding: '14px',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginBottom: 8,
          }}>
            <div style={{
              fontFamily: 'var(--font-mono)', fontSize: 10,
              color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
            }}>Calibración · holdouts</div>
            <window.Chip tone="good" size="sm">pase</window.Chip>
          </div>
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr auto auto auto',
            gap: '6px 10px', alignItems: 'center',
          }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', letterSpacing: '0.06em' }}>ciclo</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', letterSpacing: '0.06em', textAlign: 'right' }}>C₈₀</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', letterSpacing: '0.06em', textAlign: 'right' }}>C₉₅</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--muted)', letterSpacing: '0.06em', textAlign: 'right' }}>Brier</div>
            {window.CALIBRATION.holdouts.map((h, i) => (
              <React.Fragment key={i}>
                <div style={{ fontSize: 11.5 }}>{h.cycle}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}>
                  {(h.c80 * 100).toFixed(0)}%
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}>
                  {(h.c95 * 100).toFixed(0)}%
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}>
                  {h.brierR1.toFixed(2)}
                </div>
              </React.Fragment>
            ))}
          </div>
          <div style={{
            marginTop: 10, paddingTop: 10, borderTop: '0.5px dashed var(--line)',
            fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ink-soft)',
            display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6,
          }}>
            <div>r̂ max <b>{window.CALIBRATION.diagnostics.rHatMax}</b></div>
            <div>ESS min <b>{window.CALIBRATION.diagnostics.bulkEssMin}</b></div>
            <div>divs <b>{window.CALIBRATION.diagnostics.divergences}</b></div>
          </div>
        </div>
      </div>

      {/* Intervention simulator */}
      <div style={{ padding: '14px 14px 0' }}>
        <div style={{
          background: 'var(--card)', border: '0.5px solid var(--line)',
          borderRadius: 14, padding: '14px',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginBottom: 6,
          }}>
            <div style={{
              fontFamily: 'var(--font-mono)', fontSize: 10,
              color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
            }}>Simulador de intervención</div>
            <button onClick={onIntervention} style={{
              border: 'none', background: 'transparent', cursor: 'pointer',
              fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--accent)',
            }}>Registro →</button>
          </div>
          <p style={{
            margin: '0 0 10px', fontSize: 11.5, color: 'var(--ink-soft)', lineHeight: 1.4,
          }}>
            Si un candidato es inhabilitado, el posterior se reparte
            proporcionalmente entre los demás. Pruebe en seco:
          </p>
          <SimIntervention onSimulate={simulateIntervention} />
        </div>
      </div>

      {/* Methodology details */}
      <div style={{ padding: '14px 18px 0' }}>
        <h3 style={{
          margin: '0 0 6px', fontFamily: 'var(--font-display)',
          fontWeight: 500, fontSize: 16,
        }}>Componentes del modelo</h3>
        {[
          ['Agregador de encuestas', 'Estado-espacial bayesiano sobre todas las casas. Pesos por tamaño muestral y por sesgo histórico estimado.'],
          ['Fundamentos', 'Regresión sobre incumbencia partidaria, PIB, inflación, remesas, índice de seguridad, tendencia de sentimiento.'],
          ['Combinador presidencial', '10k simulaciones Monte Carlo de 1ra vuelta. Matriz de transferencia para 2da vuelta aprendida de 2007/2011/2015/2019/2023.'],
          ['Sentimiento', 'spaCy es_core_news_sm + pysentimiento BETO, por oración × entidad. Peso activo en el modelo: 0 (pendiente de validar)'],
          ['Gate de calibración', 'C₈₀≥0.78 · C₉₅≥0.92 · Brier R1≤0.15 · r̂<1.01 · ESS>400. Bloqueo automático si falla.'],
          ['Intervenciones', 'Transformaciones a nivel posterior. Toda intervención requiere --reason y --operator y se auditan.'],
        ].map(([t, d], i) => (
          <div key={i} style={{
            padding: '10px 0',
            borderBottom: '0.5px dashed var(--line)',
          }}>
            <div style={{ fontWeight: 600, fontSize: 12.5, color: 'var(--ink)' }}>{t}</div>
            <div style={{ fontSize: 11.5, color: 'var(--ink-soft)', lineHeight: 1.45, marginTop: 2 }}>{d}</div>
          </div>
        ))}
      </div>

      {/* Stable URL */}
      <div style={{
        margin: '14px 14px 0', padding: '12px 14px',
        background: 'var(--ink)', color: 'var(--paper)',
        borderRadius: 12,
        fontFamily: 'var(--font-mono)', fontSize: 10.5, lineHeight: 1.5,
      }}>
        <div style={{ opacity: 0.5, marginBottom: 4 }}>GET</div>
        <div>api.polityc.gt/v1/forecast/presidential</div>
        <div style={{ opacity: 0.6, marginTop: 6, fontSize: 9.5 }}>
          ETag + Cache-Control · 503 durante silencio electoral
        </div>
      </div>
    </div>
  );
}

function PipelineDiagram() {
  const stages = [
    { id: 'data',  label: 'Datos',     sub: '5 casas' },
    { id: 'agg',   label: 'Agregador', sub: 'state-space' },
    { id: 'fund',  label: 'Fundam.',   sub: '6 vars' },
    { id: 'comb',  label: 'Combinador',sub: '10k sims' },
    { id: 'gate',  label: 'Gate',      sub: 'C₈₀·C₉₅' },
    { id: 'pub',   label: 'Publica',   sub: 'is_pub=T' },
  ];
  return (
    <div>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 4,
        alignItems: 'stretch',
      }}>
        {stages.map((s, i) => (
          <div key={s.id} style={{
            background: i === 4 ? 'var(--accent-soft)' : 'color-mix(in oklch, var(--ink) 5%, transparent)',
            borderRadius: 6, padding: '6px 2px',
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2,
            position: 'relative', minWidth: 0,
          }}>
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 600,
              color: i === 4 ? 'oklch(0.4 0.13 50)' : 'var(--ink)',
              textAlign: 'center', whiteSpace: 'nowrap',
              overflow: 'hidden', textOverflow: 'clip', maxWidth: '100%',
            }}>{s.label}</span>
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--muted)',
              textAlign: 'center', lineHeight: 1.2, whiteSpace: 'nowrap',
              overflow: 'hidden', maxWidth: '100%',
            }}>{s.sub}</span>
            {i < stages.length - 1 && (
              <span style={{
                position: 'absolute', right: -6, top: '50%',
                transform: 'translateY(-50%)',
                color: 'var(--muted)', fontSize: 11, zIndex: 1,
                background: 'var(--card)', width: 8, height: 12,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>›</span>
            )}
          </div>
        ))}
      </div>
      <div style={{
        marginTop: 10, paddingTop: 8, borderTop: '0.5px dashed var(--line)',
        fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)',
        lineHeight: 1.4,
      }}>
        Go API ← LISTEN forecast_ready ← NOTIFY · Python escribe · Cron systemd
      </div>
    </div>
  );
}

function SimIntervention({ onSimulate }) {
  const [selected, setSelected] = React.useState(null);
  const candidates = window.CANDIDATES.filter(c => !c.isOther);
  return (
    <div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        {candidates.map(c => {
          const on = selected === c.id;
          return (
            <button key={c.id} onClick={() => setSelected(on ? null : c.id)}
                    style={{
                      padding: '4px 10px', borderRadius: 100,
                      background: on ? c.color : 'transparent',
                      border: `0.5px solid ${on ? c.color : 'var(--line)'}`,
                      color: on ? 'var(--paper)' : 'var(--ink)',
                      fontFamily: 'var(--font-body)', fontSize: 11, fontWeight: on ? 600 : 500,
                      cursor: 'pointer',
                    }}>
              <span style={{
                display: 'inline-block', width: 5, height: 5, borderRadius: 5,
                background: on ? 'var(--paper)' : c.color, marginRight: 4,
              }} />
              {c.last}
            </button>
          );
        })}
      </div>
      {selected && <SimImpact id={selected} />}
      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button onClick={() => { onSimulate && onSimulate(selected); }}
                disabled={!selected}
                style={{
                  flex: 1, padding: '8px 10px', borderRadius: 8,
                  background: selected ? 'var(--ink)' : 'var(--line)',
                  color: selected ? 'var(--paper)' : 'var(--muted)',
                  border: 'none', cursor: selected ? 'pointer' : 'not-allowed',
                  fontFamily: 'var(--font-body)', fontSize: 11.5, fontWeight: 500,
                }}>Aplicar al pronóstico</button>
        <button onClick={() => setSelected(null)}
                style={{
                  padding: '8px 10px', borderRadius: 8,
                  background: 'transparent', color: 'var(--ink-soft)',
                  border: '0.5px solid var(--line)', cursor: 'pointer',
                  fontFamily: 'var(--font-body)', fontSize: 11.5,
                }}>Reiniciar</button>
      </div>
    </div>
  );
}

function SimImpact({ id }) {
  const target = window.CANDIDATES.find(c => c.id === id);
  const others = window.CANDIDATES.filter(c => !c.isOther && c.id !== id);
  const totalOther = others.reduce((s, c) => s + c.mean, 0);
  return (
    <div style={{
      background: 'color-mix(in oklch, var(--ink) 4%, transparent)',
      padding: '8px 10px', borderRadius: 8, fontSize: 11, lineHeight: 1.5,
    }}>
      <div style={{ marginBottom: 4 }}>
        <b>{target.last}</b> queda fuera. Su masa de{' '}
        <b style={{ fontFamily: 'var(--font-mono)' }}>{target.mean.toFixed(1)}%</b>{' '}
        se redistribuye proporcionalmente:
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {others.slice(0, 3).map(c => {
          const delta = (target.mean * c.mean / totalOther);
          return (
            <div key={c.id} style={{
              display: 'flex', gap: 6, alignItems: 'center',
              fontFamily: 'var(--font-mono)', fontSize: 10,
              fontVariantNumeric: 'tabular-nums',
            }}>
              <span style={{ width: 5, height: 5, borderRadius: 5, background: c.color }} />
              <span style={{ flex: 1 }}>{c.last}</span>
              <span style={{ color: 'var(--muted)' }}>{c.mean.toFixed(1)} →</span>
              <span style={{ color: c.color, fontWeight: 600 }}>{(c.mean + delta).toFixed(1)}</span>
              <span style={{ color: 'oklch(0.45 0.13 145)' }}>+{delta.toFixed(1)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

Object.assign(window, {
  CandidateDetail, RunoffScreen, MethodologyScreen,
  PipelineDiagram, SimIntervention,
});
