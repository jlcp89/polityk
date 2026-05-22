# Architecture & Implementation Plan: A Public Web Application to Forecast Guatemala's 2027 General Elections

## TL;DR
- **Build a Go+Python pipeline that scrapes TSE, news RSS, polls, INE and Google Trends into SQLite/DuckDB on the IdeaPad; train a Bayesian hierarchical model in PyMC for the presidential race (with two-round simulation), a department-level D'Hondt simulator for the 160 congressional seats (128 distritales + 32 lista nacional), and a partial-pooling municipal model that borrows strength across the 340 municipalities via demographics; serve a static Astro site from Cloudflare Pages backed by a Go JSON API exposed through Cloudflare Tunnel.** This is the only architecture that fits a Celeron/4–8 GB laptop while delivering a credible, probabilistic, publication-grade forecast.
- **The biggest data risk is not modeling — it is data availability.** TSE publishes only PDFs and HTML (no CSV/JSON), the 2023 Memoria Electoral was still unpublished as of early 2026, TREP will be replaced for 2027, and 11 parties from 2023 have been cancelled, leaving 28 parties with active "personalidad jurídica vigente" per TSE data reported by Canal Antigua (February 9, 2026). Plan for heavy PDF parsing, HTML-table scraping with a real browser User-Agent, and a tolerance for partial data.
- **Legal: Guatemala forbids publication of polls and "estudios de opinión" only in the 36 hours before each round** (Constitutional Court ruling on expediente 1699-2018, 23 April 2019, which struck down the 2016 15-day rule and restored the original 36-hour window). Your forecasts are legal up until 36 hours before each election day; you must take the site dark from ~6 PM local Friday to ~6 PM local Sunday on both rounds. Bake a "blackout switch" into the app.

## Key Findings

### A. The 2027 Electoral System
- **President & VP**: Two-round majority (>50%) system; if no candidate exceeds 50% in the first round, the top two go to a runoff. Per International IDEA's 2025 report *Preserving Elections in Guatemala*, "all 10 presidential elections have needed a run-off election between the two leading candidates after the first round" since the 1985 return to democracy — a fact also confirmed by IFES (2023). Plan for a runoff as the default scenario. Date pattern (based on 2023): first round ~last Sunday of June 2027, runoff ~20 August 2027.
- **Congress**: 160 seats. **128 elected from 23 multi-member districts** (Guatemala department is split into "Distrito Central" — 11 seats — and "Distrito de Guatemala" — 19 seats; the other 21 departments are single districts ranging from 2 seats (El Progreso, Baja Verapaz, Zacapa) to 10 (Huehuetenango)). **32 elected from a single national list**. Closed party lists, **D'Hondt** highest-averages method applied independently in each district and to the national list.
- **Municipalities**: 340 mayors + corporación municipal (concejales + síndicos) elected together as a slate. Allocation of seats within each corporation is also proportional (plurality for alcalde + D'Hondt for concejales).
- **Also on the ballot**: 20 PARLACEN (Central American Parliament) seats — out of scope for v1, but the scraper should ingest these results anyway for completeness.

### B. Free Public Data Sources (Confirmed)

**Official electoral data (TSE):**
- `tse.org.gt` — institutional site. **Returns HTTP 403 to bare scrapers**; you must spoof a real browser User-Agent (and ideally use Cloudflare Workers as a fetch proxy if blocks persist).
- `tse.org.gt/comunicacion/publicaciones/memorias/memorias-electorales` — Memoria Electoral PDFs hosted under `/images/memoriaselec/` (e.g., `mlb2019.pdf`); 2014, 2015, 2017, 2018, 2019 confirmed. **2023 Memoria Electoral not yet published as of May 2026** (TSE Director of Logistics López said in October 2023 they were still "preparing the information and data the Memoria Electoral 2023 entails"). Each is a multi-hundred-page PDF with tables — requires `pdfplumber`/`camelot` extraction. Mirror on Scribd available for the 2019 edition (906 pages).
- `resultados2019.tse.org.gt` — 2019 results with a **"Datos abiertos: Excel"** export button on every table (most scrape-friendly historical source).
- `trep.gt`, `primeraeleccion.trep.gt`, `segundaeleccion.trep.gt` — 2023 preliminary results, per-mesa PDFs of Acta 4 accessible via Department → Municipality → Centro → Mesa drill-down. ~122,000 actas total. **No bulk download**; the only way to harvest is to crawl the JSON behind the UI. **TREP will not be reused in 2027** — TSE has announced an in-house replacement system (per Prensa Libre). Monitor `tse.org.gt` quarterly for the announcement.
- `tse.org.gt/index.php/sistema-de-estadisticas/estadisticas-de-empadronamiento` — Padrón aggregated by department, municipality, age and sex (HTML reports, no CSV). 2023 total: 9,361,068 registered citizens.
- `tse.org.gt/index.php/reg-ciudadanos/organizaciones-politicas/121-listados-partidos-politicos` — current list of registered parties (HTML only).

**Currently registered parties (early-to-mid 2026 snapshot):** 28 parties with active legal status (personalidad jurídica vigente) per TSE data reported by Canal Antigua (February 9, 2026): "28 son partidos con personalidad jurídica vigente y 28 son comités pro formación." Emisoras Unidas (May 10, 2026), citing TSE's Deyanira Herrera, puts the figure at 25 registered parties ahead of 2027 — the gap reflects parties whose appeals against cancellation are still pending. Newest registrations are **Servir** (Carlos Pineda) and **Fuerza por Guatemala** (Mauricio Radford). Eleven 2023 parties were cancelled by the Registro de Ciudadanos for failing the 5%/no-curul rule: PAN, Podemos, Partido Republicano, FCN-Nación, Partido Humanista, Unión Republicana, Partido Popular Guatemalteco, PIN, Poder, MLP, and Mi Familia. **Movimiento Semilla's cancellation is "vigente" but under appeal** — treat its 2027 eligibility as a runtime flag in the model.

**News (RSS available — these are your sentiment + event firehose):**
- **Prensa Libre**: `prensalibre.com/feed`, `prensalibre.com/guatemala/politica/feed`.
- **La Hora**: `lahora.gt` feed.
- **Soy502, Plaza Pública, Publinews, Emisoras Unidas, República, Agencia Guatemalteca de Noticias, Guatemala.com**: all have RSS (confirmed by FeedSpot's curated Guatemalan news list).
- **No RSS / requires scraping**: Nómada (largely defunct), elPeriódico (defunct since 2023), Diario de Centro América (scrape from `dca.gob.gt`).

**Polls (no API; scrape HTML or PDFs):**
- **CID Gallup** publishes blog-style PDFs at `cidgallup.com`.
- **ProDatos** publishes through Prensa Libre (Encuesta Libre).
- **Borge y Asociados**, **Fundación Libertad y Desarrollo** (often partnered with CID Gallup) — published via news media.
- Wikipedia aggregator at `en.wikipedia.org/wiki/Opinion_polling_for_the_2027_Guatemalan_general_election` (page will appear closer to election) is your fallback poll database — use the Wikipedia API, not scrape.

**Demographics & socioeconomic:**
- **INE**: `ine.gob.gt`, `datos.ine.gob.gt` (open-data portal — currently advertises only 3 datasets), `geoportal.ine.gob.gt`. Census 2018 microdata downloadable. Population projections to 2035 by municipality available.
- **SEGEPLAN**: `datos.segeplan.gob.gt` — poverty, beca recipients, ranking municipal — directly relevant for municipal-race feature engineering.
- **MINFIN**: `datos.minfin.gob.gt` — public-finance open data (transfers to municipalities are correlated with incumbent re-election rates).
- **SENACYT-managed national portals**: `datos.gob.gt` / `datos.senacyt.gob.gt` — national open-data portal (>100 datasets, mixed quality, no elections data).

**Structured knowledge bases:**
- **Wikidata** (SPARQL endpoint `query.wikidata.org/sparql`) — politicians (`P39 position held`), parties (`P102`), electoral districts (`P768`). Use for canonical candidate-to-party mappings and Wikipedia-fed biographical metadata.
- **Wikipedia** (en + es) — past election results tables, ideal for backfill of 2003–2023.
- **IFES Election Guide** (`electionguide.org`), **IPU Parline** (`data.ipu.org`) — clean structured summaries.

**Search/popularity:**
- **Google Trends** via the unofficial `pytrends` Python library — free, no API key. The official pytrends GitHub README warns: "60 seconds of sleep between requests (successful or not) appears to be the correct amount once you reach the limit. (Replicated on 2 networks)." For exploratory use, ScrapingBee documents a minimum 3–5 second gap between requests. Build a robust backoff.

**Social media — practical reality:**
- **Twitter/X**: Free API is gone; scraping is now technically prohibited by ToS and adversarial. **Do not rely on it.**
- **Bluesky**: free public AT-Proto firehose — viable but very low Guatemalan adoption.
- **YouTube Data API v3**: free tier 10,000 quota units/day. Use for video-comment sentiment on candidate channels.
- **Reddit JSON API**: `reddit.com/r/Guatemala/.json` — small but politically engaged community.
- **Facebook public pages**: technically scraping a logged-out version is feasible (use `chromedp` with a residential IP), but Facebook ToS forbid it — **only fetch Open-Graph metadata of links shared elsewhere**, not the page content directly.
- **TikTok unofficial libraries** (e.g., `TikTokApi`): brittle, frequent breakage, ToS-risky — skip for v1.
- **Telegram**: public-channel scraping via `telethon` (Python) is legal and stable — useful for monitoring partisan channels.

### C. ML / Prediction Approach

**Why Bayesian hierarchical models, not plain regression or LLMs:**
- Guatemalan polling is sparse (~5–15 national polls per cycle) and pollster house-effects are large; frequentist regression overfits.
- Municipal races have N=340 with very thin per-unit history → must pool partial information across municipalities. The canonical reference is García Montalvo, Papaspiliopoulos & Stumpf-Fétizon, "Bayesian forecasting of electoral outcomes with new parties' competition," *European Journal of Political Economy*, vol. 59(C), pp. 52–70 (2019); arXiv:1612.03073, which explicitly proposes "a Bayesian hierarchical structure for the fundamental model that synthesises data at the provincial, regional and national level" — exactly the multilevel structure Guatemala needs.
- You need calibrated **probability distributions**, not point estimates — Bayesian posteriors give this natively.

**Recommended model stack:**
1. **Poll-aggregation layer (national level)**: Drew Linzer / Pierre-Antoine Kremp style state-space model in PyMC, treating each pollster as having an unknown bias drawn from a hierarchical prior. Reference implementation: `github.com/fonnesbeck/election_pycast`.
2. **Fundamentals layer**: regression with incumbency, party-of-government penalty, GDP growth, inflation, remittance flow, security indicators. Trained on 2003–2023 elections (5 cycles).
3. **Presidential forecast**: weighted combination of poll-aggregator + fundamentals → posterior distribution over first-round vote shares for each candidate → Monte Carlo simulate 10,000 first rounds → for each iteration with no >50%, draw a runoff result conditional on first-round shares (using a learned "second-round swing" matrix from 2007/2011/2015/2019/2023 runoffs).
4. **Congressional forecast (160 seats)**: Hierarchical multinomial in PyMC over 23 districts × N_parties. Likelihood: closed-list vote shares per district. Prior pools across districts by department-level demographics (urbanity, % indigenous, poverty rate from SEGEPLAN, age-distribution from INE). For each posterior sample, run a deterministic **D'Hondt allocator in Go** (fast and verifiable) against the 11/19/3/5/2/6/3/3/4/7/5/3/9/10/8/2/9/4/3/2/3/3/4 + 32 seat structure. Output: posterior over seats per party.
5. **Municipal forecast (340 races)**: Partial-pooling model — each municipal race shares a global Dirichlet prior over party shares, plus department-level random effects, plus municipality-specific incumbency and demographic features. For municipalities with no polls (the vast majority), the prediction is essentially "what the demographic-twin municipalities are doing nationally" + 2023 result + incumbency. This is where you must show **very wide credible intervals** in the UI.

**Sentiment analysis (Spanish, CPU-only on a Celeron):**
- Use `pysentimiento` (`finiteautomata/beto-sentiment-analysis`) — POS/NEG/NEU labels, BETO base, trained on Spanish TASS. Quantize to INT8 with `optimum` + `onnxruntime` (drops the 439 MB model to ~110 MB and roughly triples CPU throughput).
- Alternative for tighter memory: `distiluse-base-multilingual-cased` (135 MB) for embeddings + a tiny logistic-regression classifier you train yourself on a small labeled set of Guatemalan political headlines (~500 manually labeled examples will get to ~80% accuracy).
- Use sentiment as **a feature into the fundamentals layer**, not as a primary signal — sentiment on news doesn't directly translate to votes, but trend changes do.

**Uncertainty quantification (must-have for public credibility):**
- Always show 80% and 95% credible intervals, never point estimates.
- For the presidential race, display the **full posterior density** as a violin plot.
- For Congress, show seat distributions as fan charts with min/median/max plausible seats per major party.
- For municipalities, show win probability + "confidence tier" (high/medium/low) based on the entropy of the posterior.

### D. Architecture for the Lenovo IdeaPad 1

**Hardware budget (worst case):** Intel Celeron N4020 / 4 GB RAM / 128 GB SSD. Realistic working RAM available to services after Linux: ~2.5 GB. CPU: 2 cores @ 1.1 GHz boost 2.8 GHz.

**Component picks:**

| Layer | Recommendation | Why |
|---|---|---|
| OS | Debian 12 minimal (no GUI) | Smallest footprint, long support |
| Database (primary, OLTP) | **SQLite with WAL mode** | Zero RAM overhead, single-file, perfect for write-light/read-heavy workload; the entire 2023 results dataset (~122k actas × ~10 columns) is ~50 MB |
| Database (analytics) | **DuckDB** (in same process as Python ML) | 20–50× faster than SQLite on aggregations; reads SQLite files directly via the `sqlite_scanner` extension; columnar — analytical queries that would OOM in Pandas run fine |
| ETL orchestration | **Custom Go scheduler** + systemd timers | Avoids Prefect (~300 MB resident) and Dagster entirely. A 200-line Go program with `robfig/cron` is enough |
| Scraping | **Colly v2** (HTTP) + **chromedp** (JS-rendered pages only when necessary) | Colly: rate limiting, retries, cookie jar, robots.txt support built in. chromedp launches headless Chromium only when needed — costs ~300 MB so use sparingly |
| RSS ingestion | **`mmcdole/gofeed`** | Tiny, robust, handles RSS+Atom+JSONFeed |
| PDF extraction | **Python: `pdfplumber` for text tables, `camelot-py` for ruled tables** | Run on demand in a separate process so memory is reclaimed |
| ML | **Python 3.11 + PyMC 5 + ArviZ + scikit-learn + statsmodels + polars** (NOT pandas — 2-5× less RAM) | PyMC's NumPyro backend on CPU runs single-chain in ~200 MB for this model size |
| Sentiment | **transformers + optimum + onnxruntime** with INT8-quantized BETO | Inference at ~200 headlines/min on Celeron |
| Caching | **In-process LRU (Go: `hashicorp/golang-lru`) + SQLite as durable cache** | Redis (~80 MB resident) is overkill; you have one machine, you don't need a network cache |
| Go↔Python IPC | **REST over Unix socket OR shared SQLite "jobs" table** | NATS is great but adds a daemon (40 MB) and complexity you don't need for one box. Simplest robust option: Go writes a "predict_request" row to SQLite, a Python worker polls it every 30s. Use **NATS only if you outgrow this** |
| HTTP API | **Go net/http + chi router** | ~12 MB resident, handles thousands of req/s easily |
| Frontend | **Astro (static, hosted on Cloudflare Pages)** + client-side `<canvas>` charts (Chart.js or Apache ECharts) | Pages = free, global CDN, no load on your laptop. Astro generates per-municipality and per-department static pages (340 + 22 + 1) at build time; the API only serves the JSON forecast and "live" updates |
| Tunnel | **Cloudflare Tunnel (cloudflared)** with the Go API listening on localhost:8080 | Free, no port-forwarding, DDoS protection at the edge |
| Cache offload | **Cloudflare cache rules** with 5-minute TTL on `/api/forecast/*` | Means the vast majority of public traffic never touches the laptop |
| Storage offload | **Cloudflare R2** for historical raw scrapes (free tier 10 GB) | Keep only the latest 30 days of raw HTML/PDF on the laptop; archive older to R2 |

**Memory budget (target):**
- Linux + sshd + cloudflared: ~400 MB
- Go scrapers + API: ~150 MB
- SQLite (no separate process): 0
- Python ML worker (only running during forecast jobs): peaks at ~1.2 GB, then exits
- DuckDB analytics (called from Python or via duckdb CLI): peak 800 MB during weekly rebuilds
- Headroom: ~700 MB

**Why NOT PostgreSQL:** Postgres in default config uses ~250 MB resident and has a query-planner overhead; for a single-writer workload, SQLite+DuckDB matches its features at a fraction of the cost. You only need Postgres if multiple processes write concurrently, which you can avoid by design.

**Why NOT Airflow/Kubernetes/Spark/Kafka:** Airflow scheduler+webserver+worker triple is ~1 GB. Kafka requires a JVM. Spark requires another JVM. None fit. Cron + Go binaries do everything you need.

### E. Deployment & Ops

**Container strategy:**
- Use **Docker Compose with resource limits** for everything except the Python ML worker. The ML worker should run as a systemd one-shot service triggered by a timer (or by a Go process via `exec`) so RAM is freed between runs.
- All Go binaries: statically compiled, ~15 MB each, run with `Restart=always` in systemd.
- Sample compose stack: `cloudflared`, `api` (Go), `scraper-news` (Go cron), `scraper-tse` (Go cron), `nats` (optional, only if needed later).

**Backup strategy (laptop = single point of failure):**
- `litestream` replicating SQLite to Cloudflare R2 in real time (free, ~5 MB resident, well-known pattern).
- Nightly `duckdb EXPORT DATABASE` to a tarball, also pushed to R2.
- Weekly `borg backup` to an external USB drive at home.
- Keep all model code, scrapers and seed data in a private GitHub repo so rebuilding the laptop = `git clone + docker compose up`.

**Monitoring:**
- **Uptime Kuma** (10 MB Go-equivalent, dockerized) for external uptime checks (Cloudflare Tunnel availability, API endpoints).
- **Loki + Promtail** is too heavy. Instead: `journalctl` + a tiny Go log-tailer that pushes ERROR-level lines to a Discord/Telegram webhook.
- Health endpoint `/health` returns DB size, last scrape timestamps, last successful forecast timestamp.
- Cloudflare Analytics (free) gives you traffic stats without any local agent.

**Realistic traffic expectation:**
- IdeaPad can serve ~50–100 req/s of plain JSON before saturating; with Cloudflare cache at 5-min TTL, edge will absorb the vast majority of repeat requests.
- On election night (worst case), expect a peak of ~5,000 concurrent viewers if the site gets press attention. The static Astro pages on Cloudflare Pages handle this trivially; only "live actualizar" buttons hit the API. Set the cache TTL on the API to 60 seconds on election day to allow fresh data through.

### F. Legal / Ethical

- **Polling blackout (LEPP Art. 223 inc. c)**: Publication of polls and "estudios de opinión" is prohibited during the **36 hours before each election round** (restored from 15 days by Constitutional Court ruling on expediente 1699-2018, 23 April 2019). **Forecasts based on aggregated polls almost certainly fall under "estudio de opinión"** — take the entire prediction page offline from 6 PM local Friday through 6 PM local Sunday on each election day. Implement a feature flag triggered by a cron job; display a legal notice ("Por mandato de la LEPP, las predicciones están suspendidas hasta las 18:00 h del día de la elección") instead.
- **Liquor ban (Art. 223 inc. d)** is not relevant to your site but happens in the same window — useful contextual info.
- **Disclaimer requirements**: No specific Guatemalan disclosure standard for forecasters exists yet, but adopt the FiveThirtyEight/Economist norms: list every model assumption, list every data source with timestamps, show the credible interval prominently, and add a permanent footer disclaimer: *"Este sitio publica pronósticos probabilísticos, no resultados oficiales. Los únicos resultados oficiales son los del Tribunal Supremo Electoral."*
- **Methodology page**: Required for credibility; publish your priors, model code (link to GitHub), update cadence and known biases.
- **Privacy**: Do not store personally identifiable voter data. The Padrón is aggregated only. Use Cloudflare Web Analytics (cookieless) instead of Google Analytics.
- **Robots.txt**: Respect TSE, Prensa Libre, La Hora and Soy502 robots.txt. Rate-limit scrapers to ≤1 req/sec per domain with 5-second jitter, and identify yourself in the User-Agent (`MyForecastBot/1.0 (+https://yourdomain.gt/about)`).

### G. Roadmap & Phasing

Assume start = June 2026 (12 months before first round). Election day(s): ~last Sunday of June 2027 + 20 August 2027.

**Phase 1 — Foundations (Jun–Aug 2026)**
- Provision Lenovo: Debian + Docker + cloudflared + Astro on Cloudflare Pages stub.
- Buy domain on Cloudflare; configure tunnel; one "hello world" public endpoint live.
- Build the **Go scraper for TSE Memorias Electorales (2011, 2015, 2019 PDFs)** and parse them into normalized tables in SQLite. Target schema: `elections (year, round, level, party_id, district_id, votes, seats)`.
- Backfill historical results for 2003–2023 using a one-time hybrid of Wikipedia tables + PDF extraction + the 2019 Datos Abiertos Excel.
- Stand up RSS ingestion for the 10 outlets named above; store raw article text + timestamp + URL.
- Stand up Wikidata SPARQL pull for parties + candidates.
- **Milestone: historical database is complete and queryable; the website shows a "histórico" page.**

**Phase 2 — Modeling backbone (Sep–Nov 2026)**
- Implement the D'Hondt simulator in Go (unit-test against 2019 and 2023 actual seat allocations — must reproduce them exactly).
- Implement the PyMC presidential poll-aggregation model; backtest against the 2015, 2019, 2023 first rounds.
- Implement the hierarchical congressional model; backtest seat predictions for 2019 and 2023.
- Implement the municipal partial-pooling model; backtest on 2019→2023 transitions for the 340 municipalities.
- **Milestone: end-to-end pipeline can produce a forecast for the *2023* election using only pre-June-2023 data, and the predictions are reasonable.**

**Phase 3 — Live data & UI polish (Dec 2026–Feb 2027)**
- Watch TSE for the announcement of the 2027 electoral calendar (typically January 2027 convocatoria); register the new candidates and parties as they're inscribed.
- Activate poll scraping (CID Gallup, ProDatos, Borge — likely to publish their first 2027 polls in Q1 2027).
- Add sentiment-analysis pipeline (BETO INT8) on the news firehose.
- Build the public UI: presidential page (violin posterior), Congress page (fan chart by party + interactive seat map), 340 municipal pages (small multiples + searchable list), methodology page.
- Add the legal blackout switch.
- **Milestone: first public-facing forecast published, ~5 months before election day, with full methodology page.**

**Phase 4 — Pre-election ramp (Mar–Jun 2027)**
- Increase forecast cadence from weekly to daily as polls intensify.
- Add reliability monitoring (Uptime Kuma alerts).
- Run a load test using `vegeta` against the API.
- **Milestone (4 weeks pre-election): freeze new features; only bug fixes.**

**Phase 5 — Election night & runoff (Jun & Aug 2027)**
- Toggle blackout 36h before each round (automated).
- After polls close, switch the homepage to a **results-tracking mode**: scrape TSE's new (post-TREP) result system as the actas come in; display "real-time vs. forecast" overlays.
- Publish a post-mortem within 2 weeks: forecast error by level, calibration plots, lessons learned.

## Recommendations

1. **Start with the database schema, not the scrapers.** Design a normalized schema for `parties`, `candidates`, `districts`, `municipalities`, `results (year, round, level, district_id, party_id, votes, seats)`, `polls`, `news_articles`, `sentiment_scores`. Get this right *before* you write a single scraper, because changing it later costs you everything.

2. **Hard-code the 23-district seat allocation** from LEPP Art. 205 as a constant in your codebase: `{Distrito Central: 11, Distrito Guatemala: 19, Sacatepéquez: 3, Chimaltenango: 5, El Progreso: 2, Escuintla: 6, Santa Rosa: 3, Sololá: 3, Totonicapán: 4, Quetzaltenango: 7, Suchitepéquez: 5, Retalhuleu: 3, San Marcos: 9, Huehuetenango: 10, Quiché: 8, Baja Verapaz: 2, Alta Verapaz: 9, Petén: 4, Izabal: 3, Zacapa: 2, Chiquimula: 3, Jalapa: 3, Jutiapa: 4, Nacional: 32}` summing to 160. Verify summation on every CI build.

3. **Prioritize PDF parsing infrastructure.** TSE publishes only PDF Memorias Electorales — invest a week in building a robust `pdfplumber` + `camelot` pipeline with table-detection unit tests against the 2019 Memoria as ground truth. This will pay back tenfold when the 2023 Memoria finally lands.

4. **Don't scrape Twitter/X, don't scrape Facebook page content.** Skip these and pour the saved effort into Telegram + Reddit + YouTube comments (which are stable, free, and legal). You will lose less than you think — Guatemalan political discourse is heavily on Facebook, but unscraped news + Telegram + YouTube comments capture a large share of the signal at a small fraction of the legal/operational risk.

5. **Use SQLite + DuckDB, not Postgres, until proven necessary.** A clear escalation trigger: if you ever need >1 concurrent writer or >100 concurrent readers hitting raw SQL (not API), revisit. Until then, the simplicity is a feature.

6. **Ship a static-first frontend.** Make Cloudflare Pages do the heavy lifting; the IdeaPad only serves the JSON delta API. Astro + island components is the lowest-RAM, highest-fidelity option for SSR/SSG mixed content.

7. **Plan for TREP's replacement.** TSE has publicly stated TREP will not be reused in 2027. Build the 2027 results-scraper as a separate module (`internal/resultados2027/`) that is empty until the new system is announced, probably late 2026 or Q1 2027. Have a contingency: if there's no machine-readable endpoint, fall back to scraping `tse.org.gt`'s preliminary HTML or partnering with Mirador Electoral / Plaza Pública's citizen-observation network.

8. **Calibrate, then promote.** Don't publicize the forecast until backtesting shows ≥95% credible intervals actually cover the truth ≥95% of the time on the 2019 and 2023 holdouts. Bad calibration in the first published forecast will permanently damage credibility.

9. **Open-source from day one.** Push the code to GitHub under a permissive license. This (a) attracts contributors, (b) preempts accusations of partisan bias, (c) is how all credible forecasters (538, Economist, Wisevoter) operate.

10. **Engage local civic-tech.** Reach out to Fundación Libertad y Desarrollo, Acción Ciudadana, CIEN, Mirador Electoral, and Diálogos GT. They have polling data, civic-tech credibility, and may give you early access to non-public datasets.

**Benchmarks/thresholds that would change these recommendations:**
- If RAM upgrades to 16 GB+ → consider PostgreSQL primary + DuckDB analytics; consider running PyMC with NUTS + 4 chains.
- If daily traffic exceeds 10,000 unique visitors → move the API to Cloudflare Workers (serverless) and use the laptop only as an ETL node.
- If TSE publishes a real open-data CSV portal → drop a large share of the PDF parsing code and reallocate that engineering time to model improvements.
- If polling firms publish only 0–3 polls before April 2027 → de-emphasize the poll-aggregation layer and lean harder on fundamentals + sentiment + 2023-baseline regression.

## Caveats

- **The 2023 Memoria Electoral has not been published as of May 2026**, per TSE statements that they were "preparing" it. Until it appears, the most reliable certified source for 2023 results is the TSE press release (Acuerdo 1659-2023 / 1361-2023 for the oficialización) and trep.gt aggregates. Treat 2023 numbers as provisional in your DB.
- **TSE political instability**: TSE magistrates faced criminal investigations after 2023 and a new magistratura (2026–2032) just took posts. Institutional behavior — including what data they publish and when — may diverge from 2019/2023 patterns. Build for "TSE will publish less than they did in 2023," not more.
- **Movimiento Semilla's status is unresolved.** Cancellation by Juzgado Séptimo Penal is "vigente" but under appeal at TSE. The model needs a configurable flag per party: `is_eligible_2027`. Reassess monthly.
- **Polling in Guatemala is thin and house-effect-prone.** The final ProDatos/Encuesta Libre poll for the 2023 first round (fieldwork June 5–14, 2023; n=1,202; ±2.8% margin) placed Arévalo at 2.9% of valid votes; he actually received ~15.5% — a miss of approximately 12.6 percentage points. ProDatos' own post-election analysis (published in Prensa Libre) acknowledged that Arévalo and Mulet were the only two of 22 candidates who "registraron desplazamientos fuera del margen de error establecido para este instrumento." Don't expect Nate Silver levels of precision; design for tail events.
- **The model will not capture institutional shocks** (party cancellations after registration, candidate disqualifications, fraud allegations). These were dominant in 2023 and likely will be in 2027. Build a manual "intervention" mechanism that lets you ratchet a candidate's probability to zero overnight if disqualified.
- **The recommendation to use Bayesian hierarchical models is opinionated.** A simpler stacked-ensemble (poll average + 2023 baseline + light regression) would also work and is easier to debug. If you find PyMC fights you, fall back to scikit-learn `BayesianRidge` + bootstrap resampling — it will be approximately 80% as good with a fraction of the math.
- **Hardware caveat**: A Celeron N4020 with 4 GB RAM is genuinely tight for PyMC. If you have the option to upgrade RAM to 8 GB (~$25 SODIMM if the IdeaPad has a free slot — check the model first; some IdeaPad 1 SKUs solder RAM), do it before writing any code — it doubles your headroom and eliminates the most common failure mode (OOM during model sampling).
- **No source rates Guatemalan election forecasting models specifically** — the methodology recommendations here adapt approaches from Spain (García Montalvo, Papaspiliopoulos & Stumpf-Fétizon, *European Journal of Political Economy* 59, 2019), France (pollsposition.com PyMC models), and US 538/Economist work. Cross-cultural generalization is imperfect; build a humility margin into your published intervals.