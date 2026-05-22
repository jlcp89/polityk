// app.jsx — root component for polityc

// Palettes — warm-paper based, all curated to keep candidate colors readable.
const PALETTES = {
  paper:  ['#faf6ee', '#1f1a14', '#c66a4b'],   // warm paper + ink + terracotta
  bone:   ['#f4ede0', '#221e15', '#a35c45'],   // bone + deeper ink + rust
  linen:  ['#f7f3ea', '#27201a', '#6b8a5a'],   // linen + ink + sage accent
  granite:['#f1eee6', '#1a1814', '#5e7b94'],   // light granite + slate accent
};

// Type pairings
const TYPE_PAIRS = {
  editorial:  { display: '"Newsreader", Georgia, serif',           body: '"DM Sans", system-ui, sans-serif',         mono: '"JetBrains Mono", ui-monospace, monospace' },
  modern:     { display: '"Instrument Serif", Georgia, serif',     body: '"Manrope", system-ui, sans-serif',          mono: '"JetBrains Mono", ui-monospace, monospace' },
  civic:      { display: '"IBM Plex Serif", Georgia, serif',       body: '"IBM Plex Sans", system-ui, sans-serif',    mono: '"IBM Plex Mono", ui-monospace, monospace' },
};

const THEMES = {
  light: {
    paper: 'var(--p-paper)', ink: 'var(--p-ink)',
    card: '#ffffff',
    inkSoft: 'color-mix(in oklch, var(--p-ink) 70%, var(--p-paper))',
    muted: 'color-mix(in oklch, var(--p-ink) 45%, var(--p-paper))',
    line: 'color-mix(in oklch, var(--p-ink) 12%, var(--p-paper))',
    accent: 'var(--p-accent)',
    accentSoft: 'color-mix(in oklch, var(--p-accent) 18%, var(--p-paper))',
  },
  dark: {
    paper: '#1a1612', ink: '#f3ece0',
    card: '#221d17',
    inkSoft: '#cdc4b5',
    muted: '#8a8275',
    line: '#332c25',
    accent: '#d98668',
    accentSoft: 'color-mix(in oklch, #d98668 22%, #1a1612)',
  },
  sepia: {
    paper: '#ece1c8', ink: '#3a2a18',
    card: '#f3ebd6',
    inkSoft: '#5e4a30',
    muted: '#8c785a',
    line: '#d4c5a4',
    accent: '#a04822',
    accentSoft: 'color-mix(in oklch, #a04822 18%, #ece1c8)',
  },
};

const DENSITY = {
  compact: { pad: 12, gap: 8, radius: 10 },
  regular: { pad: 16, gap: 12, radius: 14 },
  comfy:   { pad: 20, gap: 16, radius: 16 },
};

// ───────────────────────────────────────────────────────────

function App() {
  const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
    "palette": "paper",
    "typePair": "editorial",
    "density": "regular",
    "chartStyle": "violin",
    "theme": "light",
    "freshness": "fresh"
  }/*EDITMODE-END*/;

  const [t, setTweak] = window.useTweaks(TWEAK_DEFAULTS);

  // App state
  const [screen, setScreen] = React.useState('home');
  const [candidateOpen, setCandidateOpen] = React.useState(null);
  const [ciLevel, setCiLevel] = React.useState(80);
  const [round, setRound] = React.useState(1);
  const [scrubWeek, setScrubWeek] = React.useState(null);
  const [interventionsOpen, setInterventionsOpen] = React.useState(false);
  const [menuOpen, setMenuOpen] = React.useState(false);

  // Apply CSS variables based on tweaks
  React.useEffect(() => {
    const root = document.getElementById('polityc-root');
    if (!root) return;
    const pal = PALETTES[t.palette] || PALETTES.paper;
    const theme = THEMES[t.theme] || THEMES.light;
    const fonts = TYPE_PAIRS[t.typePair] || TYPE_PAIRS.editorial;
    const dens = DENSITY[t.density] || DENSITY.regular;

    // Palette base — only used in light theme directly
    root.style.setProperty('--p-paper', pal[0]);
    root.style.setProperty('--p-ink', pal[1]);
    root.style.setProperty('--p-accent', pal[2]);

    root.style.setProperty('--paper', theme.paper);
    root.style.setProperty('--ink', theme.ink);
    root.style.setProperty('--ink-soft', theme.inkSoft);
    root.style.setProperty('--muted', theme.muted);
    root.style.setProperty('--line', theme.line);
    root.style.setProperty('--accent', theme.accent);
    root.style.setProperty('--accent-soft', theme.accentSoft);
    root.style.setProperty('--card', theme.card);

    root.style.setProperty('--font-display', fonts.display);
    root.style.setProperty('--font-body', fonts.body);
    root.style.setProperty('--font-mono', fonts.mono);

    root.style.setProperty('--pad', `${dens.pad}px`);
    root.style.setProperty('--gap', `${dens.gap}px`);
    root.style.setProperty('--radius', `${dens.radius}px`);
  }, [t]);

  // If blackout state, all screens become the blackout splash.
  const isBlackout = t.freshness === 'blackout';

  return (
    <div id="polityc-root" style={{
      width: '100vw', height: '100vh', overflow: 'hidden',
      background: '#1d1814',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <ScaleToFit>
        <Phone>
          <window.AppBar onMenu={() => setMenuOpen(o => !o)} freshnessState={t.freshness} />
          <div style={{
            flex: 1, overflowY: 'auto', overflowX: 'hidden',
            background: 'var(--paper)', position: 'relative',
            fontFamily: 'var(--font-body)', color: 'var(--ink)',
          }}>
            {isBlackout ? (
              <window.BlackoutSplash />
            ) : screen === 'home' ? (
              <window.HomeScreen
                chartStyle={t.chartStyle}
                ciLevel={ciLevel} setCiLevel={setCiLevel}
                density={t.density}
                freshness={t.freshness}
                round={round} setRound={setRound}
                scrubWeek={scrubWeek} setScrubWeek={setScrubWeek}
                onCandidate={(id) => setCandidateOpen(id)}
                onRunoff={() => setScreen('runoff')}
                onMethod={() => setScreen('method')}
              />
            ) : screen === 'runoff' ? (
              <window.RunoffScreen
                ciLevel={ciLevel}
                freshness={t.freshness}
                onCandidate={(id) => setCandidateOpen(id)}
              />
            ) : screen === 'method' ? (
              <window.MethodologyScreen
                freshness={t.freshness}
                onIntervention={() => setInterventionsOpen(true)}
                simulateIntervention={(id) => {
                  // mock: doesn't actually mutate posteriors here
                  console.log('Simulate intervention on', id);
                }}
              />
            ) : screen === 'status' ? (
              <window.StatusScreen
                freshness={t.freshness}
                onIntervention={() => setInterventionsOpen(true)}
              />
            ) : null}

            {/* Candidate detail sheet */}
            {candidateOpen && (
              <window.CandidateDetail
                candidateId={candidateOpen}
                onClose={() => setCandidateOpen(null)}
                ciLevel={ciLevel} chartStyle={t.chartStyle}
              />
            )}

            {/* Interventions sheet */}
            {interventionsOpen && (
              <window.BottomSheet open={true} onClose={() => setInterventionsOpen(false)} maxHeight={0.92}>
                <window.InterventionsScreen onBack={() => setInterventionsOpen(false)} />
              </window.BottomSheet>
            )}

            {/* Overflow menu */}
            {menuOpen && (
              <div style={{
                position: 'absolute', top: 6, right: 12, zIndex: 50,
                background: 'var(--card)', borderRadius: 10,
                boxShadow: '0 8px 28px rgba(0,0,0,0.18), 0 0 0 0.5px var(--line)',
                overflow: 'hidden', minWidth: 200,
              }} onClick={(e) => e.stopPropagation()}>
                {[
                  ['Registro de intervenciones', () => { setMenuOpen(false); setInterventionsOpen(true); }],
                  ['Compartir pronóstico', () => { setMenuOpen(false); }],
                  ['Acerca de polityc', () => { setMenuOpen(false); }],
                ].map(([label, fn], i) => (
                  <button key={i} onClick={fn} style={{
                    width: '100%', padding: '10px 14px', textAlign: 'left',
                    border: 'none', background: 'transparent', cursor: 'pointer',
                    fontSize: 12, color: 'var(--ink)',
                    borderTop: i > 0 ? '0.5px solid var(--line)' : 'none',
                  }}>{label}</button>
                ))}
              </div>
            )}
            {menuOpen && (
              <div style={{
                position: 'absolute', inset: 0, zIndex: 40,
              }} onClick={() => setMenuOpen(false)} />
            )}
          </div>
          {!isBlackout && (
            <window.BottomNav current={screen} onChange={setScreen} />
          )}
        </Phone>
      </ScaleToFit>

      <window.TweaksPanel>
        <window.TweakSection label="Aesthetic">
          <window.TweakRadio label="Tipografía" value={t.typePair}
            options={[
              { value: 'editorial', label: 'Editorial' },
              { value: 'modern',    label: 'Moderno' },
              { value: 'civic',     label: 'Cívico' },
            ]}
            onChange={(v) => setTweak('typePair', v)} />
          <window.TweakColor label="Paleta" value={t.palette}
            options={[
              { value: 'paper', label: 'Paper' },
              { value: 'bone', label: 'Bone' },
              { value: 'linen', label: 'Linen' },
              { value: 'granite', label: 'Granite' },
            ].map(o => ({ value: o.value, colors: PALETTES[o.value] })).map(o => o.colors)}
            onChange={(v) => {
              // map the array back to the palette key
              const found = Object.entries(PALETTES).find(([k, arr]) =>
                JSON.stringify(arr).toLowerCase() === JSON.stringify(v).toLowerCase());
              setTweak('palette', found ? found[0] : 'paper');
            }} />
          <window.TweakRadio label="Tema" value={t.theme}
            options={[
              { value: 'light', label: 'Claro' },
              { value: 'dark',  label: 'Oscuro' },
              { value: 'sepia', label: 'Sepia' },
            ]}
            onChange={(v) => setTweak('theme', v)} />
          <window.TweakRadio label="Densidad" value={t.density}
            options={[
              { value: 'compact', label: 'Compacto' },
              { value: 'regular', label: 'Regular' },
              { value: 'comfy',   label: 'Amplio' },
            ]}
            onChange={(v) => setTweak('density', v)} />
        </window.TweakSection>

        <window.TweakSection label="Visualización">
          <window.TweakSelect label="Estilo de gráfico" value={t.chartStyle}
            options={[
              { value: 'violin', label: 'Violín (densidad simétrica)' },
              { value: 'ridge',  label: 'Cresta' },
              { value: 'bar',    label: 'Barra con IC' },
              { value: 'dot',    label: 'Punto + bigotes' },
            ]}
            onChange={(v) => setTweak('chartStyle', v)} />
        </window.TweakSection>

        <window.TweakSection label="Estado de datos">
          <window.TweakSelect label="Frescura" value={t.freshness}
            options={[
              { value: 'fresh',    label: 'Al día (verde)' },
              { value: 'warn6',    label: '6–24 h (amarillo)' },
              { value: 'warn24',   label: '24–72 h (ámbar)' },
              { value: 'stale',    label: '>72 h (rojo)' },
              { value: 'blackout', label: 'Silencio electoral (503)' },
            ]}
            onChange={(v) => setTweak('freshness', v)} />
        </window.TweakSection>
      </window.TweaksPanel>
    </div>
  );
}

// — Phone frame ———————————————————————————————————————

function Phone({ children }) {
  return (
    <div style={{
      width: 412, height: 892, borderRadius: 44, padding: 6,
      background: 'linear-gradient(160deg, #3a3128 0%, #1c1812 60%, #2a2218 100%)',
      boxShadow: '0 30px 80px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.04) inset',
    }}>
      <div style={{
        width: '100%', height: '100%', borderRadius: 38, overflow: 'hidden',
        background: 'var(--paper)',
        display: 'flex', flexDirection: 'column',
        position: 'relative',
      }}>
        <StatusBar />
        {children}
        <NavBar />
      </div>
    </div>
  );
}

function StatusBar() {
  return (
    <div style={{
      height: 38, padding: '8px 22px 0',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      background: 'var(--paper)',
      position: 'relative', flexShrink: 0,
    }}>
      <span style={{
        fontFamily: 'var(--font-body)', fontSize: 13, fontWeight: 600,
        color: 'var(--ink)', fontVariantNumeric: 'tabular-nums',
      }}>9:41</span>
      <div style={{
        position: 'absolute', left: '50%', top: 6, transform: 'translateX(-50%)',
        width: 110, height: 26, background: '#0a0805', borderRadius: 100,
      }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, color: 'var(--ink)' }}>
        {/* signal */}
        <svg width="16" height="11" viewBox="0 0 16 11">
          <rect x="0" y="7" width="3" height="4" fill="currentColor" />
          <rect x="4.5" y="5" width="3" height="6" fill="currentColor" />
          <rect x="9" y="2.5" width="3" height="8.5" fill="currentColor" />
          <rect x="13.5" y="0" width="3" height="11" fill="currentColor" opacity="0.4" />
        </svg>
        {/* wifi */}
        <svg width="14" height="11" viewBox="0 0 14 11">
          <path d="M7 10.5 L8.5 8.7 Q7 7.5 5.5 8.7 Z" fill="currentColor" />
          <path d="M7 9 Q4 6.5 1 9.5 L0 8.5 Q4 4 8 7.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M7 5.5 Q3 2.5 -1 6 L-2 5 Q3 0 10 5" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.4" />
        </svg>
        {/* battery */}
        <svg width="24" height="11" viewBox="0 0 24 11">
          <rect x="0.5" y="0.5" width="21" height="10" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1" />
          <rect x="22.2" y="3.5" width="1.5" height="4" rx="0.6" fill="currentColor" />
          <rect x="2" y="2" width="14" height="7" rx="1" fill="currentColor" />
        </svg>
      </div>
    </div>
  );
}

function NavBar() {
  return (
    <div style={{
      height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--paper)', flexShrink: 0,
    }}>
      <div style={{
        width: 134, height: 4, borderRadius: 4,
        background: 'color-mix(in oklch, var(--ink) 45%, transparent)',
      }} />
    </div>
  );
}

// — Scale-to-fit wrapper ————————————————————————————

function ScaleToFit({ children, designW = 412, designH = 892 }) {
  const [scale, setScale] = React.useState(1);
  React.useEffect(() => {
    const update = () => {
      const ww = window.innerWidth, wh = window.innerHeight;
      const m = 32;
      const s = Math.min((ww - m) / designW, (wh - m) / designH);
      setScale(Math.min(1.4, s));
    };
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);
  return (
    <div style={{
      width: designW * scale, height: designH * scale,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        width: designW, height: designH,
        transform: `scale(${scale})`, transformOrigin: 'center center',
        flexShrink: 0,
      }}>
        {children}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
