// data.jsx — fixture data for the polityc forecast
// 2027 Guatemalan presidential race, as of forecast run 2026-05-21
// All numbers are illustrative — calibrated to plausible early-cycle shape.

const CANDIDATES = [
  {
    id: 'torres',
    last: 'Torres',
    first: 'Sandra',
    party: 'UNE',
    partyFull: 'Unidad Nacional de la Esperanza',
    mean: 21.4, sd: 5.8, skew: 0.1,
    winR1: 0.92, // qualifies for runoff
    winPres: 0.34, // wins presidency
    color: '#c66a4b',
    incumbent: false,
    runs: 4,
    notes: 'Cuarta candidatura. Base territorial fuerte en el corredor seco.',
  },
  {
    id: 'rios',
    last: 'Ríos',
    first: 'Zury',
    party: 'VALOR',
    partyFull: 'Movimiento Político VALOR',
    mean: 15.8, sd: 5.2, skew: 0,
    winR1: 0.68,
    winPres: 0.22,
    color: '#b08a3a',
    runs: 4,
    notes: 'Inscripción ratificada por la CC en 2025.',
  },
  {
    id: 'herrera',
    last: 'Herrera',
    first: 'Karin',
    party: 'Semilla',
    partyFull: 'Movimiento Semilla',
    mean: 13.1, sd: 5.6, skew: -0.05,
    winR1: 0.49,
    winPres: 0.18,
    color: '#6b8a5a',
    runs: 1,
    incumbentParty: true,
    notes: 'Elegibilidad partidaria pendiente de resolución. Ver registro de intervenciones.',
  },
  {
    id: 'conde',
    last: 'Conde',
    first: 'Manuel',
    party: 'VAMOS',
    partyFull: 'Vamos por una Guatemala Diferente',
    mean: 11.2, sd: 4.4, skew: 0,
    winR1: 0.31,
    winPres: 0.09,
    color: '#8a5a7c',
    runs: 1,
    notes: 'Continuidad del oficialismo Giammattei.',
  },
  {
    id: 'mulet',
    last: 'Mulet',
    first: 'Edmond',
    party: 'Cabal',
    partyFull: 'Partido Político Cabal',
    mean: 9.3, sd: 4.1, skew: 0,
    winR1: 0.22,
    winPres: 0.06,
    color: '#5e7b94',
    runs: 3,
    notes: 'Tercer intento. Voto de centro-urbano.',
  },
  {
    id: 'cabrera',
    last: 'Cabrera',
    first: 'Thelma',
    party: 'MLP',
    partyFull: 'Movimiento para la Liberación de los Pueblos',
    mean: 7.6, sd: 3.6, skew: 0.05,
    winR1: 0.14,
    winPres: 0.04,
    color: '#a07a8a',
    runs: 2,
    notes: 'Inscripción presidencial en revisión.',
  },
  {
    id: 'arzu',
    last: 'Arzú',
    first: 'Roberto',
    party: 'DCG',
    partyFull: 'Democracia Cristiana Guatemalteca',
    mean: 5.4, sd: 3.0, skew: 0,
    winR1: 0.05,
    winPres: 0.01,
    color: '#8a4b35',
    runs: 2,
    notes: '',
  },
  {
    id: 'otros',
    last: 'Otros',
    first: '',
    party: '—',
    partyFull: 'Otros candidatos + indecisos + nulo/blanco',
    mean: 16.2, sd: 4.0, skew: 0,
    winR1: 0,
    winPres: 0,
    color: '#b0a698',
    isOther: true,
    notes: 'Agregado: candidatos restantes + voto nulo/blanco + indecisos.',
  },
];

// — Density helpers ———————————————————————————————————————

// Gaussian-with-tunable-skew PDF sample on a grid.
function density(mean, sd, skew = 0, lo = 0, hi = 50, n = 90) {
  const pts = [];
  for (let i = 0; i < n; i++) {
    const x = lo + (hi - lo) * (i / (n - 1));
    const z = (x - mean) / sd;
    // Skew-normal approx: phi(z) * (1 + erf(alpha*z/sqrt(2)))
    const phi = Math.exp(-0.5 * z * z);
    const skewMult = 1 + skew * Math.tanh(z * 1.2);
    pts.push({ x, y: phi * skewMult });
  }
  // Normalize peak to 1
  const peak = Math.max(...pts.map(p => p.y));
  return pts.map(p => ({ x: p.x, y: p.y / peak }));
}

// Quantile (approx via Z table) for symmetric normal.
function quantile(mean, sd, q) {
  // inverse normal via Beasley-Springer-Moro approximation
  const a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
             1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00];
  const b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
             6.680131188771972e+01, -1.328068155288572e+01];
  const c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
             -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00];
  const d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
             3.754408661907416e+00];
  const plow = 0.02425, phigh = 1 - plow;
  let z;
  if (q < plow) {
    const u = Math.sqrt(-2 * Math.log(q));
    z = (((((c[0]*u+c[1])*u+c[2])*u+c[3])*u+c[4])*u+c[5]) /
        ((((d[0]*u+d[1])*u+d[2])*u+d[3])*u+1);
  } else if (q <= phigh) {
    const u = q - 0.5;
    const r = u * u;
    z = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*u /
        (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1);
  } else {
    const u = Math.sqrt(-2 * Math.log(1 - q));
    z = -(((((c[0]*u+c[1])*u+c[2])*u+c[3])*u+c[4])*u+c[5]) /
        ((((d[0]*u+d[1])*u+d[2])*u+d[3])*u+1);
  }
  return mean + z * sd;
}

function intervals(c) {
  return {
    q025: Math.max(0, quantile(c.mean, c.sd, 0.025)),
    q10:  Math.max(0, quantile(c.mean, c.sd, 0.10)),
    q50:  c.mean,
    q90:  quantile(c.mean, c.sd, 0.90),
    q975: quantile(c.mean, c.sd, 0.975),
  };
}

// — Trajectory data ———————————————————————————————————————

// Weekly forecast trajectory, going back ~9 months to 2025-08
function makeTrajectory() {
  const weeks = 40;
  const traj = {};
  CANDIDATES.forEach(c => {
    const series = [];
    let v = c.mean - 4 + Math.random() * 2;
    const target = c.mean;
    for (let w = 0; w < weeks; w++) {
      // Drift toward target with small noise
      const pull = (target - v) * 0.12;
      const noise = (Math.sin(w * 0.7 + c.mean) * 0.6 + Math.cos(w * 0.4) * 0.4);
      v = v + pull + noise * 0.5;
      // CI width shrinks toward present
      const widthFactor = 1 + (weeks - w) / weeks * 0.6;
      const sd = c.sd * widthFactor * 0.85;
      series.push({
        w,
        median: v,
        q10: Math.max(0, v - 1.28 * sd),
        q90: v + 1.28 * sd,
        q025: Math.max(0, v - 1.96 * sd),
        q975: v + 1.96 * sd,
      });
    }
    // Anchor final point at exactly c.mean
    series[series.length - 1] = {
      w: weeks - 1,
      median: c.mean,
      q10: Math.max(0, c.mean - 1.28 * c.sd),
      q90: c.mean + 1.28 * c.sd,
      q025: Math.max(0, c.mean - 1.96 * c.sd),
      q975: c.mean + 1.96 * c.sd,
    };
    traj[c.id] = series;
  });
  return traj;
}

const TRAJECTORY = makeTrajectory();

// — Pollsters ———————————————————————————————————————

const POLLSTERS = [
  { id: 'cid',   name: 'CID Gallup',          biasMean: -1.2, biasSd: 2.4, n: 14, color: '#1f1a14' },
  { id: 'prod',  name: 'ProDatos',            biasMean: +2.6, biasSd: 3.1, n: 11, color: '#1f1a14' },
  { id: 'fund',  name: 'Fund. Libertad',      biasMean: +0.8, biasSd: 2.0, n: 8,  color: '#1f1a14' },
  { id: 'borge', name: 'Borge y Asoc.',       biasMean: -0.3, biasSd: 1.6, n: 9,  color: '#1f1a14' },
  { id: 'lp',    name: 'La Prensa / IPSOS',   biasMean: +0.1, biasSd: 1.4, n: 6,  color: '#1f1a14' },
];

// Recent polls per candidate (last ~12 weeks). Each entry: pollster id, weeks ago, share, n.
function makePolls(c) {
  const polls = [];
  POLLSTERS.forEach((p, pi) => {
    const count = 2 + (pi % 2);
    for (let i = 0; i < count; i++) {
      const weeksAgo = 1 + Math.floor(Math.random() * 11);
      const bias = p.biasMean * (c.id === 'torres' ? 0.6 : c.id === 'herrera' ? -0.5 : 0.3);
      const share = Math.max(0, c.mean + bias + (Math.random() - 0.5) * c.sd * 1.4);
      const n = 1000 + Math.floor(Math.random() * 800);
      const moe = 1.96 * Math.sqrt(share * (100 - share) / n);
      polls.push({ p: p.id, w: weeksAgo, share: +share.toFixed(1), n, moe: +moe.toFixed(1) });
    }
  });
  return polls.sort((a, b) => a.w - b.w);
}

const POLLS = {};
CANDIDATES.forEach(c => { POLLS[c.id] = makePolls(c); });

// — Runoff matrix ———————————————————————————————————————
// Conditional probability P(row wins runoff | row vs column makes 2nd round)

const RUNOFF_PAIRS = (() => {
  const ranked = CANDIDATES.filter(c => !c.isOther).slice(0, 6);
  const cells = {};
  const homeAdvantage = {
    torres: 0.46,    // historically struggles in runoffs
    rios: 0.55,
    herrera: 0.62,   // urban + Semilla brand
    conde: 0.42,
    mulet: 0.58,
    cabrera: 0.40,
  };
  ranked.forEach(r => {
    cells[r.id] = {};
    ranked.forEach(c => {
      if (r.id === c.id) return;
      // anti-incumbent skew + base ideological distance
      const ha = homeAdvantage[r.id] ?? 0.5;
      const op = homeAdvantage[c.id] ?? 0.5;
      let p = ha / (ha + op);
      // Probability this pairing actually happens (joint qualify prob)
      const joint = r.winR1 * c.winR1 * 0.6;
      cells[r.id][c.id] = { prob: +(p * 100).toFixed(0), joint: +(joint * 100).toFixed(0) };
    });
  });
  return cells;
})();

// — Calibration ———————————————————————————————————————

const CALIBRATION = {
  modelVersion: '1.2.0-rc4',
  runId: 'fcst-2026-05-21-094412z',
  generatedAt: '2026-05-21T09:44:12Z',
  nextRun: '2026-05-28T09:00:00Z',
  cadence: 'Semanal hasta enero 2027',
  holdouts: [
    { cycle: '2019 1ra vuelta', c80: 0.83, c95: 0.96, brierR1: 0.07, status: 'pass' },
    { cycle: '2019 2da vuelta', c80: 0.79, c95: 0.94, brierR1: 0.05, status: 'pass' },
    { cycle: '2023 1ra vuelta', c80: 0.81, c95: 0.95, brierR1: 0.12, status: 'pass' },
    { cycle: '2023 2da vuelta', c80: 0.80, c95: 0.94, brierR1: 0.04, status: 'pass' },
  ],
  diagnostics: {
    rHatMax: 1.004,
    bulkEssMin: 814,
    divergences: 0,
    chains: 4,
    samples: 4000,
    warmup: 2000,
    targetAccept: 0.95,
  },
};

const INTERVENTIONS = [
  {
    id: 'INT-2026-008',
    when: '2026-04-18T16:22:00Z',
    candidate: 'Pineda, Carlos',
    party: 'Prosperidad Ciudadana',
    kind: 'inelegibilidad',
    operator: 'maintainer@polityc',
    reason: 'Resolución TSE 0381-2026: finiquito vencido. Posterior fijado a 0; renormalización aplicada al resto.',
    appliedTo: 'fcst-2026-04-18-162200z',
    status: 'active',
  },
  {
    id: 'INT-2026-007',
    when: '2026-03-02T11:08:00Z',
    candidate: 'Estrada, Mario',
    party: 'UCN',
    kind: 'inelegibilidad',
    operator: 'maintainer@polityc',
    reason: 'Sentencia firme — inhabilitación política. Posterior fijado a 0.',
    appliedTo: 'fcst-2026-03-02-110800z',
    status: 'active',
  },
  {
    id: 'INT-2026-006',
    when: '2026-02-14T09:15:00Z',
    candidate: 'Semilla (partido)',
    party: 'Movimiento Semilla',
    kind: 'elegibilidad-flag',
    operator: 'maintainer@polityc',
    reason: 'Flag party_eligibility.eligible = TRUE tras resolución CC expediente 2421-2025.',
    appliedTo: 'fcst-2026-02-14-091500z',
    status: 'active',
  },
];

const HEALTH = {
  db: { status: 'ok', latencyMs: 4 },
  lastForecast: { at: '2026-05-21T09:44:12Z', status: 'published', runId: 'fcst-2026-05-21-094412z' },
  lastScrapes: [
    { source: 'TSE — partidos',         at: '2026-05-21T06:00:11Z', status: 'ok',   rows: 42 },
    { source: 'CID Gallup PDF',         at: '2026-05-20T18:14:33Z', status: 'ok',   rows: 1 },
    { source: 'ProDatos PDF',           at: '2026-05-19T20:01:09Z', status: 'ok',   rows: 1 },
    { source: 'RSS · 10 medios',        at: '2026-05-21T08:55:00Z', status: 'ok',   rows: 187 },
    { source: 'Wikidata SPARQL',        at: '2026-05-21T03:00:00Z', status: 'ok',   rows: 14 },
    { source: 'INE open-data',          at: '2026-05-20T03:00:00Z', status: 'ok',   rows: 8 },
    { source: 'Reddit JSON',            at: '2026-05-21T08:00:00Z', status: 'ok',   rows: 64 },
    { source: 'Bluesky firehose',       at: '2026-05-21T09:30:00Z', status: 'warn', rows: 0, note: 'reconexión a los 18 s' },
    { source: 'YouTube Data v3',        at: '2026-05-21T07:00:00Z', status: 'ok',   rows: 22 },
    { source: 'Google Trends',          at: '2026-05-21T02:00:00Z', status: 'ok',   rows: 5 },
    { source: 'Telegram (telethon)',    at: '2026-05-21T08:30:00Z', status: 'ok',   rows: 41 },
    { source: 'Wikipedia API',          at: '2026-05-20T03:00:00Z', status: 'ok',   rows: 7 },
  ],
  blackout: { enabled: false, nextWindow: '2027-06-23T06:00:00Z–2027-06-25T18:00:00Z' },
  api: { rpm: 142, p95Ms: 38, etagHitRate: 0.91 },
};

Object.assign(window, {
  CANDIDATES, POLLSTERS, POLLS, TRAJECTORY, RUNOFF_PAIRS,
  CALIBRATION, INTERVENTIONS, HEALTH,
  density, quantile, intervals,
});
