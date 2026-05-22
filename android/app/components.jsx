// components.jsx — shared UI components for polityc

// — Spanish date formatter ——————————————————————————————

function fmtDate(iso, { time = true, rel = false } = {}) {
  const d = new Date(iso);
  const now = new Date('2026-05-21T10:00:00Z');
  if (rel) {
    const diff = (now - d) / 1000;
    if (diff < 60) return 'hace unos segundos';
    if (diff < 3600) return `hace ${Math.round(diff/60)} min`;
    if (diff < 86400) return `hace ${Math.round(diff/3600)} h`;
    if (diff < 86400 * 7) return `hace ${Math.round(diff/86400)} días`;
    return d.toLocaleDateString('es-GT', { day: 'numeric', month: 'short' });
  }
  const datePart = d.toLocaleDateString('es-GT', {
    day: 'numeric', month: 'short', year: 'numeric',
  });
  if (!time) return datePart;
  const timePart = d.toLocaleTimeString('es-GT', {
    hour: '2-digit', minute: '2-digit', timeZone: 'America/Guatemala',
  });
  return `${datePart} · ${timePart} GT`;
}

// — Header (per screen) ——————————————————————————————

function ScreenHeader({ title, eyebrow, right, onBack }) {
  return (
    <div style={{
      padding: '14px 18px 10px',
      borderBottom: '0.5px solid var(--line)',
      background: 'var(--paper)',
      position: 'sticky', top: 0, zIndex: 10,
    }}>
      {eyebrow && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginBottom: 2,
        }}>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 10,
            color: 'var(--muted)', letterSpacing: '0.08em', textTransform: 'uppercase',
          }}>{eyebrow}</div>
          {right}
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8 }}>
        {onBack && (
          <button onClick={onBack} style={{
            border: 'none', background: 'transparent', padding: 0, marginRight: 2,
            cursor: 'pointer', display: 'flex', alignItems: 'center',
            color: 'var(--ink)', fontSize: 22, lineHeight: 1,
          }}>‹</button>
        )}
        <h1 style={{
          margin: 0, fontFamily: 'var(--font-display)',
          fontWeight: 500, fontSize: 28, lineHeight: 1.05,
          letterSpacing: '-0.01em', color: 'var(--ink)',
        }}>{title}</h1>
      </div>
    </div>
  );
}

// — Freshness banner ——————————————————————————————

const FRESHNESS = {
  fresh:   { tone: 'good', label: 'Pronóstico al día', sub: 'Actualizado hace 14 minutos · próximo ciclo: jueves',                  ic: '●' },
  warn6:   { tone: 'warn', label: 'Sin red',             sub: 'Mostrando la última copia en caché · 8 horas atrás',                  ic: '◐' },
  warn24:  { tone: 'warn', label: 'Datos del día anterior', sub: 'Sin nueva publicación en 32 horas · revise su conexión',           ic: '◑' },
  stale:   { tone: 'bad',  label: 'Datos vencidos',      sub: 'Última publicación hace 4 días — no representa el estado actual',     ic: '○' },
  blackout:{ tone: 'ink',  label: 'Silencio electoral',  sub: 'Pronósticos pausados por ley · expediente 1699-2018',                 ic: '■' },
};

function FreshnessBanner({ state = 'fresh' }) {
  const f = FRESHNESS[state] || FRESHNESS.fresh;
  const colors = {
    good: { bg: 'color-mix(in oklch, oklch(0.68 0.1 145) 18%, var(--paper))', fg: 'oklch(0.32 0.08 145)', dot: 'oklch(0.55 0.12 145)' },
    warn: { bg: 'color-mix(in oklch, oklch(0.78 0.13 75) 22%, var(--paper))', fg: 'oklch(0.32 0.1 60)',  dot: 'oklch(0.62 0.13 65)' },
    bad:  { bg: 'color-mix(in oklch, oklch(0.7 0.15 30) 22%, var(--paper))',  fg: 'oklch(0.36 0.13 30)', dot: 'oklch(0.55 0.16 30)' },
    ink:  { bg: 'var(--ink)', fg: 'var(--paper)', dot: 'var(--paper)' },
  };
  const c = colors[f.tone];
  return (
    <div style={{
      padding: '10px 14px', display: 'flex', gap: 10, alignItems: 'center',
      background: c.bg, color: c.fg, fontSize: 12,
      borderBottom: '0.5px solid var(--line)',
    }}>
      <span style={{
        width: 8, height: 8, borderRadius: 8, background: c.dot, flexShrink: 0,
        boxShadow: state === 'fresh' ? '0 0 0 3px color-mix(in oklch, oklch(0.55 0.12 145) 22%, transparent)' : 'none',
      }} />
      <div style={{ flex: 1, lineHeight: 1.3 }}>
        <div style={{ fontWeight: 600, fontSize: 12.5 }}>{f.label}</div>
        <div style={{ opacity: 0.85, fontSize: 11, marginTop: 1 }}>{f.sub}</div>
      </div>
    </div>
  );
}

// — Pill / chip ———————————————————————————————————————

function Chip({ children, tone = 'ink', size = 'md', style = {} }) {
  const tones = {
    ink:   { bg: 'color-mix(in oklch, var(--ink) 8%, transparent)',   fg: 'var(--ink)' },
    ghost: { bg: 'transparent', fg: 'var(--muted)', border: '0.5px solid var(--line)' },
    accent:{ bg: 'var(--accent-soft)', fg: 'oklch(0.4 0.13 50)' },
    good:  { bg: 'color-mix(in oklch, oklch(0.6 0.1 145) 14%, transparent)', fg: 'oklch(0.35 0.08 145)' },
    warn:  { bg: 'color-mix(in oklch, oklch(0.7 0.14 70) 20%, transparent)', fg: 'oklch(0.38 0.1 60)' },
  };
  const t = tones[tone] || tones.ink;
  const pad = size === 'sm' ? '2px 7px' : '3px 9px';
  const fs = size === 'sm' ? 10 : 11;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: pad, borderRadius: 100, background: t.bg, color: t.fg,
      border: t.border || 'none',
      fontFamily: 'var(--font-body)', fontSize: fs, fontWeight: 500,
      letterSpacing: '0.01em',
      ...style,
    }}>{children}</span>
  );
}

// — Bottom sheet ——————————————————————————————

function BottomSheet({ open, onClose, children, title, maxHeight = 0.85 }) {
  if (!open) return null;
  return (
    <div style={{
      position: 'absolute', inset: 0, zIndex: 100, display: 'flex',
      flexDirection: 'column', justifyContent: 'flex-end',
      background: 'rgba(20, 16, 8, 0.32)',
      backdropFilter: 'blur(2px)',
      WebkitBackdropFilter: 'blur(2px)',
      animation: 'fadeIn .18s ease-out',
    }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
           style={{
             background: 'var(--paper)',
             borderRadius: '20px 20px 0 0',
             maxHeight: `${maxHeight * 100}%`,
             overflowY: 'auto',
             animation: 'slideUp .22s cubic-bezier(.2,.7,.3,1)',
             boxShadow: '0 -8px 30px rgba(0,0,0,0.16)',
           }}>
        <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0 4px' }}>
          <div style={{ width: 40, height: 4, borderRadius: 4, background: 'var(--line)' }} />
        </div>
        {title && (
          <div style={{
            padding: '8px 18px 12px', display: 'flex',
            justifyContent: 'space-between', alignItems: 'center',
            borderBottom: '0.5px solid var(--line)',
          }}>
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 500 }}>{title}</div>
            <button onClick={onClose} style={{
              border: 'none', background: 'transparent', padding: 4,
              cursor: 'pointer', color: 'var(--muted)', fontSize: 18, lineHeight: 1,
            }}>×</button>
          </div>
        )}
        {children}
      </div>
    </div>
  );
}

// — Bottom nav tabs —————————————————————————————

function BottomNav({ current, onChange }) {
  const tabs = [
    { id: 'home',     label: 'Inicio',     icon: 'home' },
    { id: 'runoff',   label: '2da Vuelta', icon: 'cross' },
    { id: 'method',   label: 'Método',     icon: 'method' },
    { id: 'status',   label: 'Estado',     icon: 'pulse' },
  ];
  return (
    <div style={{
      display: 'flex', borderTop: '0.5px solid var(--line)',
      background: 'var(--paper)', flexShrink: 0,
    }}>
      {tabs.map(t => {
        const active = current === t.id;
        return (
          <button key={t.id} onClick={() => onChange(t.id)}
                  style={{
                    flex: 1, padding: '8px 0 6px',
                    border: 'none', background: 'transparent',
                    display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3,
                    color: active ? 'var(--ink)' : 'var(--muted)',
                    fontFamily: 'var(--font-body)', fontSize: 10.5, fontWeight: active ? 600 : 500,
                    cursor: 'pointer', position: 'relative',
                  }}>
            <NavIcon kind={t.icon} active={active} />
            <span>{t.label}</span>
            {active && (
              <span style={{
                position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)',
                width: 24, height: 2, background: 'var(--accent)', borderRadius: 2,
              }} />
            )}
          </button>
        );
      })}
    </div>
  );
}

function NavIcon({ kind, active }) {
  const s = active ? 'var(--ink)' : 'var(--muted)';
  const fw = active ? 1.8 : 1.4;
  if (kind === 'home') return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <path d="M4 11l8-7 8 7v9a1 1 0 01-1 1h-4v-6h-6v6H5a1 1 0 01-1-1v-9z"
            stroke={s} strokeWidth={fw} strokeLinejoin="round" />
    </svg>
  );
  if (kind === 'cross') return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <rect x="3" y="3" width="8" height="8" stroke={s} strokeWidth={fw} />
      <rect x="13" y="3" width="8" height="8" stroke={s} strokeWidth={fw} />
      <rect x="3" y="13" width="8" height="8" stroke={s} strokeWidth={fw} />
      <rect x="13" y="13" width="8" height="8" stroke={s} strokeWidth={fw} fill={active ? 'var(--accent-soft)' : 'none'} />
    </svg>
  );
  if (kind === 'method') return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <path d="M5 20V4M5 4h10l3 4-3 4H5" stroke={s} strokeWidth={fw} strokeLinejoin="round" />
    </svg>
  );
  if (kind === 'pulse') return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <path d="M3 12h4l2-6 4 12 2-6h6" stroke={s} strokeWidth={fw} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// — App-bar (above screen header) ——————————————————————

function AppBar({ onMenu, freshnessState }) {
  const f = FRESHNESS[freshnessState] || FRESHNESS.fresh;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '6px 14px', background: 'var(--paper)',
      borderBottom: '0.5px solid color-mix(in oklch, var(--line) 60%, transparent)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Logo />
        <span style={{
          fontFamily: 'var(--font-display)', fontSize: 16, fontWeight: 500,
          letterSpacing: '-0.005em',
        }}>polityc</span>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)',
          padding: '1px 5px', border: '0.5px solid var(--line)', borderRadius: 4,
          textTransform: 'uppercase', letterSpacing: '0.06em',
          whiteSpace: 'nowrap', flexShrink: 0,
        }}>v1 · pres</span>
      </div>
      <button onClick={onMenu} style={{
        border: 'none', background: 'transparent', padding: 4,
        display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
        color: 'var(--ink)',
      }}>
        <svg width="16" height="16" viewBox="0 0 16 16">
          <circle cx="3" cy="8" r="1.4" fill="currentColor" />
          <circle cx="8" cy="8" r="1.4" fill="currentColor" />
          <circle cx="13" cy="8" r="1.4" fill="currentColor" />
        </svg>
      </button>
    </div>
  );
}

function Logo() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20">
      {/* Stylized density curve in a circle */}
      <circle cx="10" cy="10" r="9" fill="var(--ink)" />
      <path d="M2 12 Q 5 12, 6 10 Q 7 7, 10 7 Q 13 7, 14 10 Q 15 12, 18 12"
            fill="none" stroke="var(--paper)" strokeWidth="1.6" strokeLinecap="round" />
      <circle cx="10" cy="7" r="1.4" fill="var(--accent)" />
    </svg>
  );
}

// — Empty / divider ———————————————————————————————

function Divider({ label }) {
  if (!label) return <div style={{ height: 0.5, background: 'var(--line)', margin: '12px 0' }} />;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '10px 18px' }}>
      <span style={{ flex: 1, height: 0.5, background: 'var(--line)' }} />
      <span style={{
        fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)',
        textTransform: 'uppercase', letterSpacing: '0.1em',
      }}>{label}</span>
      <span style={{ flex: 1, height: 0.5, background: 'var(--line)' }} />
    </div>
  );
}

// — Stat block ———————————————————————————————————————

function Stat({ label, value, sub, color }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--muted)',
        letterSpacing: '0.08em', textTransform: 'uppercase',
      }}>{label}</div>
      <div style={{
        fontFamily: 'var(--font-display)', fontSize: 22, fontWeight: 500,
        letterSpacing: '-0.005em', color: color || 'var(--ink)',
        fontVariantNumeric: 'tabular-nums', lineHeight: 1,
      }}>{value}</div>
      {sub && (
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 1 }}>{sub}</div>
      )}
    </div>
  );
}

Object.assign(window, {
  fmtDate, ScreenHeader, FreshnessBanner, FRESHNESS, Chip, BottomSheet,
  BottomNav, AppBar, Logo, Divider, Stat,
});
