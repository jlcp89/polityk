// screens-ops.jsx — Status (health), Interventions log, Blackout splash

// — STATUS / HEALTH DASHBOARD ——————————————————————————

function StatusScreen({ freshness, onIntervention }) {
  const H = window.HEALTH;
  return (
    <div style={{ paddingBottom: 24 }}>
      <window.FreshnessBanner state={freshness} />

      <div style={{ padding: '16px 18px 4px' }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
          marginBottom: 4,
        }}>Estado del sistema · /v1/health</div>
        <h1 style={{
          margin: 0, fontFamily: 'var(--font-display)',
          fontWeight: 500, fontSize: 28, lineHeight: 1.0,
          letterSpacing: '-0.01em', color: 'var(--ink)',
        }}>
          Vital <em style={{ fontStyle: 'italic', color: 'var(--accent)' }}>signs</em>
        </h1>
      </div>

      {/* Status pills */}
      <div style={{
        padding: '14px 14px 0',
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8,
      }}>
        <StatusCard
          label="Postgres"
          value="ok"
          sub={`${H.db.latencyMs} ms`}
          tone="good" />
        <StatusCard
          label="Última corrida"
          value="publicada"
          sub={window.fmtDate(H.lastForecast.at, { rel: true })}
          tone="good" />
        <StatusCard
          label="Silencio"
          value="off"
          sub="próx. 23 jun 27"
          tone="ghost" />
        <StatusCard
          label="API"
          value={`${H.api.rpm} rpm`}
          sub={`p95 ${H.api.p95Ms} ms · ETag ${(H.api.etagHitRate * 100).toFixed(0)}%`}
          tone="ghost" />
      </div>

      {/* Scrapers */}
      <div style={{ padding: '16px 14px 0' }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
          marginBottom: 6, paddingLeft: 4,
        }}>Scrapers · últimas corridas</div>
        <div style={{
          background: 'var(--card)', border: '0.5px solid var(--line)',
          borderRadius: 12, overflow: 'hidden',
        }}>
          {H.lastScrapes.map((s, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', padding: '8px 12px',
              gap: 10,
              borderBottom: i < H.lastScrapes.length - 1 ? '0.5px solid var(--line)' : 'none',
            }}>
              <span style={{
                width: 6, height: 6, borderRadius: 6, flexShrink: 0,
                background: s.status === 'ok' ? 'oklch(0.55 0.12 145)' :
                            s.status === 'warn' ? 'oklch(0.7 0.14 70)' :
                            'oklch(0.6 0.18 30)',
              }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 11.5, color: 'var(--ink)', whiteSpace: 'nowrap',
                              overflow: 'hidden', textOverflow: 'ellipsis' }}>{s.source}</div>
                {s.note && (
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)' }}>
                    {s.note}
                  </div>
                )}
              </div>
              <div style={{
                fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--muted)',
                textAlign: 'right', flexShrink: 0, width: 64, whiteSpace: 'nowrap',
              }}>
                <div>{window.fmtDate(s.at, { rel: true }).replace('hace ', '')}</div>
                <div style={{ fontSize: 9.5 }}>{s.rows} {s.rows === 1 ? 'fila' : 'filas'}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* API panel */}
      <div style={{ padding: '16px 14px 0' }}>
        <div style={{
          background: 'var(--ink)', color: 'var(--paper)',
          borderRadius: 12, padding: '14px',
          fontFamily: 'var(--font-mono)', fontSize: 10.5, lineHeight: 1.6,
        }}>
          <div style={{ opacity: 0.5, fontSize: 9, letterSpacing: '0.1em', marginBottom: 6 }}>
            CURL · /v1/health
          </div>
          <div style={{ opacity: 0.95 }}>
            {`{`}<br />
            {`  "db": "ok",`}<br />
            {`  "last_forecast": "2026-05-21T09:44:12Z",`}<br />
            {`  "blackout": false,`}<br />
            {`  "scrapers_24h": 12,`}<br />
            {`  "model_version": "${window.CALIBRATION.modelVersion}"`}<br />
            {`}`}
          </div>
        </div>
      </div>

      {/* Interventions link */}
      <div style={{ padding: '14px 14px 0' }}>
        <window.CardLink
          eyebrow="Registro de intervenciones"
          title={`${window.INTERVENTIONS.length} intervenciones activas`}
          sub="Inhabilitaciones, retiros y flags de elegibilidad"
          onClick={onIntervention} />
      </div>
    </div>
  );
}

function StatusCard({ label, value, sub, tone }) {
  const tones = {
    good:  { bg: 'color-mix(in oklch, oklch(0.6 0.1 145) 14%, transparent)', dot: 'oklch(0.55 0.12 145)' },
    warn:  { bg: 'color-mix(in oklch, oklch(0.7 0.14 70) 18%, transparent)', dot: 'oklch(0.62 0.14 65)' },
    bad:   { bg: 'color-mix(in oklch, oklch(0.6 0.18 30) 18%, transparent)', dot: 'oklch(0.55 0.16 30)' },
    ghost: { bg: 'var(--card)', dot: 'var(--muted)' },
  };
  const t = tones[tone] || tones.ghost;
  return (
    <div style={{
      background: t.bg, border: '0.5px solid var(--line)',
      borderRadius: 12, padding: '12px 12px 10px',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6,
      }}>
        <span style={{ width: 6, height: 6, borderRadius: 6, background: t.dot, flexShrink: 0 }} />
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 9.5,
          color: 'var(--muted)', letterSpacing: '0.06em', textTransform: 'uppercase',
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        }}>{label}</span>
      </div>
      <div style={{
        fontFamily: 'var(--font-display)', fontSize: 19, fontWeight: 500,
        color: 'var(--ink)', lineHeight: 1, fontVariantNumeric: 'tabular-nums',
      }}>{value}</div>
      {sub && (
        <div style={{
          marginTop: 3, fontFamily: 'var(--font-mono)', fontSize: 10,
          color: 'var(--ink-soft)', fontVariantNumeric: 'tabular-nums',
        }}>{sub}</div>
      )}
    </div>
  );
}

// — INTERVENTIONS LOG ——————————————————————————————

function InterventionsScreen({ onBack }) {
  return (
    <div style={{ paddingBottom: 24 }}>
      <window.ScreenHeader
        eyebrow="Auditoría · interventions"
        title="Registro de intervenciones"
        onBack={onBack} />

      <div style={{ padding: '12px 18px 4px' }}>
        <p style={{
          margin: 0, fontSize: 12, color: 'var(--ink-soft)', lineHeight: 1.5,
        }}>
          Toda intervención manual sobre el posterior requiere{' '}
          <code style={mono()}>--reason</code> y{' '}
          <code style={mono()}>--operator</code>. Se aplica como transformación
          a nivel posterior (cero + renormalización) y nunca como edición de datos crudos.
        </p>
      </div>

      <div style={{ padding: '12px 14px 0' }}>
        {window.INTERVENTIONS.map((iv, i) => (
          <div key={iv.id} style={{
            background: 'var(--card)', border: '0.5px solid var(--line)',
            borderRadius: 12, padding: '12px 14px',
            marginBottom: 8,
            position: 'relative',
            borderLeft: '3px solid ' + (iv.kind === 'inelegibilidad' ? 'oklch(0.58 0.14 30)' : 'oklch(0.6 0.12 145)'),
          }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
              marginBottom: 4,
            }}>
              <div style={{
                fontFamily: 'var(--font-mono)', fontSize: 10,
                color: 'var(--muted)', letterSpacing: '0.06em',
              }}>{iv.id}</div>
              <window.Chip tone={iv.kind === 'inelegibilidad' ? 'warn' : 'good'} size="sm">
                {iv.kind}
              </window.Chip>
            </div>
            <div style={{
              fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 500,
              color: 'var(--ink)', lineHeight: 1.15,
            }}>{iv.candidate}</div>
            <div style={{
              fontSize: 10.5, color: 'var(--muted)', marginTop: 2,
            }}>{iv.party}</div>
            <div style={{
              marginTop: 8, fontSize: 11.5, color: 'var(--ink-soft)', lineHeight: 1.45,
              fontStyle: 'italic',
            }}>"{iv.reason}"</div>
            <div style={{
              marginTop: 8, paddingTop: 8, borderTop: '0.5px dashed var(--line)',
              display: 'flex', justifyContent: 'space-between',
              fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)',
            }}>
              <span>{iv.operator}</span>
              <span>{window.fmtDate(iv.when, { rel: false })}</span>
            </div>
            <div style={{
              fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)',
              marginTop: 2,
            }}>
              Aplicado a <span style={{ color: 'var(--ink-soft)' }}>{iv.appliedTo}</span>
            </div>
          </div>
        ))}
      </div>

      <div style={{
        margin: '4px 14px 0', padding: '12px 14px',
        background: 'color-mix(in oklch, var(--ink) 4%, transparent)',
        borderRadius: 12, fontFamily: 'var(--font-mono)', fontSize: 10, lineHeight: 1.5,
        color: 'var(--ink-soft)',
      }}>
        <div style={{ color: 'var(--muted)', marginBottom: 4 }}>$ polityc interventions add</div>
        --candidate="Pineda, Carlos"<br />
        --kind=inelegibilidad<br />
        --reason="Res. TSE 0381-2026..."<br />
        --operator=maintainer@polityc
      </div>
    </div>
  );
}

function mono() {
  return {
    fontFamily: 'var(--font-mono)', fontSize: 11,
    padding: '0 4px', borderRadius: 3,
    background: 'color-mix(in oklch, var(--ink) 6%, transparent)',
  };
}

// — BLACKOUT SPLASH ——————————————————————————————

function BlackoutSplash() {
  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      background: 'var(--ink)', color: 'var(--paper)',
      padding: '40px 24px 24px',
      position: 'relative', overflow: 'hidden',
    }}>
      {/* Subtle pattern */}
      <svg viewBox="0 0 400 800" style={{
        position: 'absolute', inset: 0, opacity: 0.06, pointerEvents: 'none',
      }}>
        {Array.from({ length: 22 }).map((_, i) => (
          <line key={i} x1="0" y1={i * 40} x2="400" y2={i * 40 + 200}
                stroke="var(--paper)" strokeWidth="0.3" />
        ))}
      </svg>

      {/* Top eyebrow */}
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10,
        opacity: 0.5, letterSpacing: '0.18em', textTransform: 'uppercase',
        position: 'relative',
      }}>
        polityc · v1 presidencial
      </div>

      {/* Hero */}
      <div style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        justifyContent: 'center', position: 'relative',
      }}>
        <div style={{
          width: 56, height: 56, borderRadius: 56,
          background: 'transparent',
          border: '1px solid color-mix(in oklch, var(--paper) 40%, transparent)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          marginBottom: 24,
        }}>
          <span style={{
            width: 16, height: 16, background: 'var(--paper)', borderRadius: 2,
          }} />
        </div>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 10.5, opacity: 0.6,
          letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10,
        }}>HTTP 503 · silencio electoral</div>
        <h1 style={{
          margin: 0, fontFamily: 'var(--font-display)',
          fontSize: 38, fontWeight: 400, lineHeight: 1.0,
          letterSpacing: '-0.02em', textWrap: 'balance',
        }}>
          Hoy <em style={{ fontStyle: 'italic' }}>no</em> publicamos.
        </h1>
        <p style={{
          margin: '20px 0 0', fontSize: 14, lineHeight: 1.55,
          opacity: 0.85, textWrap: 'pretty',
        }}>
          La Corte de Constitucionalidad prohíbe difundir pronósticos
          electorales 36 horas antes de cada vuelta.
        </p>
        <p style={{
          margin: '12px 0 0', fontSize: 13, lineHeight: 1.55,
          opacity: 0.65, textWrap: 'pretty',
        }}>
          Volveremos en cuanto cierren las urnas y la ley nos lo permita.
          Ningún pronóstico en caché se mostrará durante este período.
        </p>

        <div style={{
          marginTop: 28, padding: '14px 14px',
          background: 'color-mix(in oklch, var(--paper) 5%, transparent)',
          border: '0.5px solid color-mix(in oklch, var(--paper) 12%, transparent)',
          borderRadius: 10,
          fontFamily: 'var(--font-mono)', fontSize: 10.5, lineHeight: 1.5,
        }}>
          <div style={{ opacity: 0.5, marginBottom: 4, fontSize: 9, letterSpacing: '0.1em' }}>
            VENTANA ACTIVA
          </div>
          <div>2027-06-23 06:00 GT</div>
          <div style={{ opacity: 0.55 }}>↓ 36 h</div>
          <div>2027-06-25 18:00 GT</div>
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: '0.5px dashed color-mix(in oklch, var(--paper) 20%, transparent)', opacity: 0.65, fontSize: 9.5 }}>
            Expediente 1699-2018 · CC
          </div>
        </div>
      </div>

      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 9.5, opacity: 0.45,
        textAlign: 'center', letterSpacing: '0.06em',
      }}>
        Reactivación automática · 25 jun 2027 · 18:00 GT
      </div>
    </div>
  );
}

Object.assign(window, {
  StatusScreen, StatusCard, InterventionsScreen, BlackoutSplash,
});
