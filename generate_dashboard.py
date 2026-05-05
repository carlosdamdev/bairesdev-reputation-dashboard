#!/usr/bin/env python3
"""
Genera dashboard.html a partir de bairesdev_history.csv.
Se llama automáticamente desde scraper_ratings.py, o manualmente:
    python generate_dashboard.py
"""
import csv
import json
import sys
import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HISTORY_CSV  = Path(__file__).parent / "bairesdev_history.csv"
REVIEWS_CSV  = Path(__file__).parent / "bairesdev_reviews.csv"
DASHBOARD_HTML = Path(__file__).parent / "dashboard.html"


def _latest_total_reviews() -> dict:
    """Lee el CSV de ratings más reciente y retorna {plataforma: total_reviews}."""
    import glob
    files = sorted(glob.glob(str(Path(__file__).parent / "bairesdev_ratings_*.csv")))
    if not files:
        return {}
    totals = {}
    with open(files[-1], newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                totals[r["Plataforma"]] = int(r["Cantidad de Reviews"])
            except (KeyError, ValueError):
                pass
    return totals

PLATFORMS_ORDER = ["Trustpilot", "Clutch", "Glassdoor", "TeamBlind", "Indeed"]

COLORS = {
    "Trustpilot": "#00b67a",  # verde
    "Clutch":     "#ff4500",  # rojo-naranja
    "Glassdoor":  "#38bdf8",  # celeste
    "TeamBlind":  "#a78bfa",  # violeta
    "Indeed":     "#fbbf24",  # amarillo
}


def build_data(csv_path: Path) -> dict:
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    # Filtrar solo filas con fecha de inicio en 2026
    rows = [r for r in rows if r["Fecha_Inicio_Semana"] >= "2026-01-01"]

    # Semanas únicas ordenadas
    weeks = sorted(set(int(r["Semana"]) for r in rows))

    # Fecha de inicio por semana
    week_dates = {}
    for r in rows:
        w = int(r["Semana"])
        if w not in week_dates:
            week_dates[w] = r["Fecha_Inicio_Semana"]

    # Score y nuevas reseñas por (plataforma, semana)
    raw: dict[str, dict] = {p: {} for p in PLATFORMS_ORDER}
    new_rev: dict[str, dict] = {p: {} for p in PLATFORMS_ORDER}
    for r in rows:
        p, w = r["Plataforma"], int(r["Semana"])
        if p not in raw:
            continue
        try:
            raw[p][w] = float(r["Score"])
        except (ValueError, TypeError):
            raw[p][w] = None
        new_rev[p][w] = r["Nuevas_Resenas"] if r["Nuevas_Resenas"] not in ("", "-", "None") else None

    # Arrays paralelos (None para semanas sin dato)
    scores_arr = {p: [raw[p].get(w) for w in weeks] for p in PLATFORMS_ORDER}

    current_week = max(weeks)
    current_date = week_dates[current_week]

    # KPI: delta vs semana anterior con dato, y vs semana 0
    kpi = {}
    for p in PLATFORMS_ORDER:
        curr = raw[p].get(current_week)
        # Semana anterior con dato real
        prev = None
        for w in sorted(raw[p].keys(), reverse=True):
            if w < current_week and raw[p][w] is not None:
                prev = raw[p][w]
                break
        first = raw[p].get(min(weeks))
        kpi[p] = {
            "current":     curr,
            "prev":        prev,
            "delta_week":  round(curr - prev, 2) if curr is not None and prev is not None else 0,
            "delta_total": round(curr - first, 2) if curr is not None and first is not None else 0,
        }

    # Reseñas nuevas de la semana actual (vs semana anterior)
    new_rev_arr = {}
    for p in PLATFORMS_ORDER:
        v = new_rev[p].get(current_week)
        new_rev_arr[p] = int(v) if v is not None and str(v).isdigit() else 0

    # Promedio de score por plataforma en las últimas 3 semanas
    avg3 = {}
    for p in PLATFORMS_ORDER:
        last3 = sorted(
            [(w, raw[p][w]) for w in raw[p] if raw[p][w] is not None],
            reverse=True
        )[:3]
        avg3[p] = round(sum(s for _, s in last3) / len(last3), 2) if last3 else None

    recent = _load_recent_reviews(current_week, avg3)
    latest = _load_latest_reviews(weeks=4)
    total_reviews = _latest_total_reviews()

    return {
        "platforms":     PLATFORMS_ORDER,
        "colors":        COLORS,
        "weeks":         weeks,
        "dates":         [week_dates[w] for w in weeks],
        "labels":        [f"S{w}" for w in weeks],
        "scores":        scores_arr,
        "currentWeek":   current_week,
        "currentDate":   current_date,
        "kpi":           kpi,
        "newReviews":    new_rev_arr,
        "recentReviews": recent,
        "latestReviews": latest,
        "avg3":          avg3,
        "totalReviews":  total_reviews,
        "generated":     datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _load_recent_reviews(current_week: int, avg3: dict, n: int = 50) -> list:
    if not REVIEWS_CSV.exists():
        return []
    rows = []
    with open(REVIEWS_CSV, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                rating = float(r["Rating"]) if r["Rating"] else 0
            except ValueError:
                rating = 0
            plat = r["Plataforma"]
            threshold = avg3.get(plat)
            # Solo reviews nuevas (escritas esta semana o la anterior, año actual) y bajo la media
            current_year = datetime.date.today().year
            try:
                semana_rev = int(r.get("Semana_Review") or 0)
                año_rev    = int(r.get("Año_Review") or 0)
            except (ValueError, TypeError):
                semana_rev = año_rev = 0
            if año_rev != current_year or semana_rev not in (current_week, current_week - 1):
                continue
            if threshold is None or rating == 0 or rating >= threshold:
                continue
            usuario = r.get("Usuario", "").strip()
            rows.append({
                "plataforma": plat,
                "fecha":      r["Fecha_Review"],
                "rating":     rating,
                "titulo":     r["Titulo"][:80],
                "texto":      (r["Texto"] or r["Pros"] or "")[:200],
                "puesto":     r["Puesto"][:50],
                "usuario":    usuario if usuario and usuario != "Anónimo" else "",
                "threshold":  threshold,
            })
    rows.sort(key=lambda r: r["fecha"] or "0000-00-00", reverse=True)
    return rows[:n]


def _load_latest_reviews(weeks: int = 4, n: int = 200) -> list:
    if not REVIEWS_CSV.exists():
        return []
    all_rows = []
    with open(REVIEWS_CSV, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            fecha = r.get("Fecha_Review", "")
            try:
                rating = float(r["Rating"]) if r["Rating"] else 0
            except ValueError:
                rating = 0
            usuario = r.get("Usuario", "").strip()
            all_rows.append({
                "plataforma": r["Plataforma"],
                "fecha":      fecha,
                "rating":     rating,
                "titulo":     r["Titulo"][:80],
                "texto":      (r["Texto"] or r["Pros"] or "")[:200],
                "puesto":     r["Puesto"][:50],
                "usuario":    usuario if usuario and usuario != "Anónimo" else "",
            })
    if not all_rows:
        return []
    # Rolling 4-week window from today
    cutoff = (datetime.date.today() - datetime.timedelta(weeks=weeks)).isoformat()
    dated = sorted(
        [r for r in all_rows if r["fecha"] and r["fecha"] >= cutoff],
        key=lambda r: r["fecha"],
        reverse=True
    )
    return dated[:n]


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BairesDev — Reputation Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

  :root {
    --bg:        #07090f;
    --surface:   #0d1117;
    --card:      #161b22;
    --card-hover:#1c2330;
    --border:    #21262d;
    --border2:   #30363d;
    --text:      #e6edf3;
    --muted:     #8b949e;
    --green:     #3fb950;
    --red:       #f85149;
    --neutral:   #8b949e;
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    min-height: 100vh;
  }

  /* ── Layout wrapper ─────────────────────────────────── */
  .page { max-width: 1400px; margin: 0 auto; padding: 32px 24px; }

  /* ── Header ─────────────────────────────────────────── */
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 36px;
    padding-bottom: 24px;
    border-bottom: 1px solid var(--border);
  }

  .header-left h1 {
    font-size: 1.5rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    color: var(--text);
  }
  .header-left h1 span { color: var(--muted); font-weight: 400; }

  .header-left p {
    font-size: 0.8rem;
    color: var(--muted);
    margin-top: 4px;
  }

  .header-right {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
  }

  .week-pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    background: linear-gradient(135deg, #1f2d5c, #1a2744);
    border: 1px solid #2d3f6e;
    border-radius: 9999px;
    padding: 6px 16px;
    font-size: 0.8rem;
    font-weight: 600;
    color: #93b4ff;
  }
  .week-pill .dot { width: 6px; height: 6px; border-radius: 50%; background: #4f8ef7; }

  .generated { font-size: 0.72rem; color: var(--muted); }

  /* ── Section label ───────────────────────────────────── */
  .section-label {
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--muted);
    margin-bottom: 14px;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .section-label::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
  }

  /* ── KPI grid ────────────────────────────────────────── */
  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 14px;
    margin-bottom: 36px;
  }

  .kpi-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-top: 3px solid var(--p-color);
    border-radius: 10px;
    padding: 18px 20px 16px;
    transition: background 0.15s, transform 0.15s;
    cursor: default;
  }
  .kpi-card:hover { background: var(--card-hover); transform: translateY(-2px); }

  .kpi-name {
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--p-color);
    margin-bottom: 14px;
    display: flex;
    align-items: center;
    gap: 7px;
  }
  .kpi-name::before {
    content: '';
    width: 7px; height: 7px;
    border-radius: 50%;
    background: var(--p-color);
    flex-shrink: 0;
  }

  .kpi-score {
    font-size: 2.8rem;
    font-weight: 700;
    line-height: 1;
    letter-spacing: -0.04em;
    margin-bottom: 12px;
  }

  .kpi-deltas { display: flex; flex-direction: column; gap: 5px; }

  .delta {
    font-size: 0.75rem;
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .delta .arrow { font-size: 0.65rem; }
  .delta.up   { color: var(--green); }
  .delta.down { color: var(--red); }
  .delta.flat { color: var(--muted); }
  .delta .label { color: var(--muted); font-weight: 400; }

  /* ── Chart cards ─────────────────────────────────────── */
  .chart-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 24px;
    margin-bottom: 14px;
  }
  .chart-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
  }
  .chart-card-header h2 {
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--text);
  }
  .chart-card-header p {
    font-size: 0.75rem;
    color: var(--muted);
  }

  /* ── Platform grid ───────────────────────────────────── */
  .platform-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
    margin-bottom: 14px;
  }
  /* 5 charts: wrap last row centered */
  .platform-grid .platform-card:nth-child(4) { grid-column: 1 / 2; }
  .platform-grid .platform-card:nth-child(5) { grid-column: 2 / 3; }

  .platform-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-left: 3px solid var(--p-color);
    border-radius: 10px;
    padding: 18px 20px;
    transition: background 0.15s;
  }
  .platform-card:hover { background: var(--card-hover); }

  .platform-card-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 14px;
  }
  .platform-card-header h3 {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--p-color);
  }
  .platform-card-header .score-badge {
    font-size: 1.4rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    color: var(--text);
  }
  .platform-card-header .score-badge span {
    font-size: 0.72rem;
    font-weight: 400;
    color: var(--muted);
  }

  .platform-stats {
    display: flex;
    gap: 16px;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }
  .stat { display: flex; flex-direction: column; gap: 2px; }
  .stat .s-val { font-size: 0.8rem; font-weight: 600; }
  .stat .s-lbl { font-size: 0.68rem; color: var(--muted); }
  .stat .s-val.up   { color: var(--green); }
  .stat .s-val.down { color: var(--red); }
  .stat .s-val.flat { color: var(--muted); }

  /* ── Reviews recientes ──────────────────────────────── */
  .reviews-filters {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 16px;
  }
  .filter-btn {
    padding: 5px 14px;
    border-radius: 9999px;
    border: 1px solid var(--border2);
    background: var(--card);
    color: var(--muted);
    font-size: 0.72rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
    font-family: inherit;
  }
  .filter-btn:hover, .filter-btn.active {
    background: var(--card-hover);
    color: var(--text);
    border-color: var(--border2);
  }
  .filter-btn.active { border-color: var(--text); color: var(--text); }

  .reviews-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 12px;
  }

  .review-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 18px;
    transition: background 0.15s;
  }
  .review-card:hover { background: var(--card-hover); }
  .review-card.hidden { display: none; }

  .review-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
  }

  .plat-badge {
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 3px 9px;
    border-radius: 9999px;
    background: var(--p-color);
    color: #fff;
    opacity: 0.9;
  }

  .review-meta {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.72rem;
    color: var(--muted);
  }

  .stars { color: #f0c040; letter-spacing: -1px; font-size: 0.78rem; }

  .review-title {
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 6px;
    line-height: 1.4;
  }

  .review-text {
    font-size: 0.77rem;
    color: var(--muted);
    line-height: 1.55;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .review-footer {
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid var(--border);
    font-size: 0.7rem;
    color: var(--muted);
  }

  /* ── Responsive ──────────────────────────────────────── */
  @media (max-width: 1100px) {
    .kpi-grid { grid-template-columns: repeat(3, 1fr); }
    .platform-grid { grid-template-columns: repeat(2, 1fr); }
    .platform-grid .platform-card:nth-child(4),
    .platform-grid .platform-card:nth-child(5) { grid-column: auto; }
  }
  @media (max-width: 700px) {
    .kpi-grid { grid-template-columns: repeat(2, 1fr); }
    .platform-grid { grid-template-columns: 1fr; }
    .header { flex-direction: column; align-items: flex-start; gap: 12px; }
  }
</style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <header class="header">
    <div class="header-left">
      <h1>BairesDev <span>Reputation Dashboard</span></h1>
      <p>Monitoreo semanal de scores en plataformas de reviews · 2026</p>
    </div>
    <div class="header-right">
      <div class="week-pill"><span class="dot"></span><span id="week-label">—</span></div>
      <div class="generated" id="generated-label"></div>
    </div>
  </header>

  <!-- KPIs -->
  <div class="section-label">Indicadores semana actual</div>
  <div class="kpi-grid" id="kpi-grid"></div>

  <!-- Overview chart -->
  <div class="section-label">Evolución general</div>
  <div class="chart-card">
    <div class="chart-card-header">
      <h2>Scores por plataforma</h2>
      <p>Todas las semanas relevadas</p>
    </div>
    <canvas id="overview-chart" height="85"></canvas>
  </div>

  <!-- Per-platform -->
  <div class="section-label" style="margin-top:28px;">Evolución por plataforma</div>
  <div class="platform-grid" id="platform-grid"></div>

  <!-- Recent reviews below avg -->
  <div class="section-label" style="margin-top:36px;">Nuevas reviews por debajo de la media (últimas 3 semanas)</div>
  <div class="reviews-filters" id="reviews-filters"></div>
  <div class="reviews-grid" id="reviews-grid"></div>

  <!-- Latest reviews rolling 4 weeks -->
  <div class="section-label" style="margin-top:48px;">Últimas reviews — ventana 4 semanas</div>
  <div class="reviews-filters" id="latest-filters"></div>
  <div class="reviews-grid" id="latest-grid"></div>

</div><!-- /page -->

<script>
const D = __DATA__;

/* ── Helpers ────────────────────────────────────────── */
function fmt(iso) {
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: 'short' });
}
function sign(v) { return v > 0 ? '+' : ''; }
function arrow(v) { return v > 0 ? '▲' : v < 0 ? '▼' : '→'; }
function cls(v)   { return v > 0 ? 'up' : v < 0 ? 'down' : 'flat'; }
function sc(v)    { return v !== null && v !== undefined ? v.toFixed(1) : '—'; }

/* ── Header ─────────────────────────────────────────── */
document.getElementById('week-label').textContent =
  `Semana ${D.currentWeek}  ·  ${fmt(D.currentDate)}`;
document.getElementById('generated-label').textContent =
  `Actualizado: ${D.generated}`;

/* ── KPI cards ──────────────────────────────────────── */
const kpiGrid = document.getElementById('kpi-grid');
D.platforms.forEach(p => {
  const k = D.kpi[p], color = D.colors[p];
  const dw = k.delta_week, dt = k.delta_total;
  kpiGrid.insertAdjacentHTML('beforeend', `
    <div class="kpi-card" style="--p-color:${color}">
      <div class="kpi-name">${p}</div>
      <div class="kpi-score">${sc(k.current)}</div>
      <div class="kpi-deltas">
        <div class="delta ${cls(dw)}">
          <span class="arrow">${arrow(dw)}</span>
          <strong>${dw !== 0 ? sign(dw)+Math.abs(dw).toFixed(2) : 'Sin cambio'}</strong>
          <span class="label">vs sem. anterior</span>
        </div>
        <div class="delta ${cls(dt)}">
          <span class="arrow">${arrow(dt)}</span>
          <strong>${dt !== 0 ? sign(dt)+Math.abs(dt).toFixed(2) : 'Sin cambio'}</strong>
          <span class="label">vs inicio año</span>
        </div>
      </div>
    </div>`);
});

/* ── Chart.js defaults ──────────────────────────────── */
Chart.defaults.color          = '#8b949e';
Chart.defaults.borderColor    = '#21262d';
Chart.defaults.font.family    = "Inter, system-ui, sans-serif";
Chart.defaults.font.size      = 11;

const xLabels = D.dates.map(fmt);

function baseOpts(yMin, yMax) {
  return {
    responsive: true,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: {
        position: 'top',
        labels: { usePointStyle: true, pointStyleWidth: 8, padding: 18, boxHeight: 8 }
      },
      tooltip: {
        backgroundColor: '#1c2330',
        borderColor: '#30363d',
        borderWidth: 1,
        padding: 10,
        callbacks: {
          label: c => ` ${c.dataset.label}: ${c.parsed.y !== null ? c.parsed.y.toFixed(1) : '—'}`
        }
      }
    },
    scales: {
      x: {
        grid:  { color: '#0d1117' },
        ticks: { maxRotation: 45, maxTicksLimit: 20 }
      },
      y: {
        min: yMin, max: yMax,
        grid:  { color: '#161b22' },
        ticks: { stepSize: 0.1, callback: v => v.toFixed(1) }
      }
    }
  };
}

/* ── Overview chart ─────────────────────────────────── */
new Chart(document.getElementById('overview-chart'), {
  type: 'line',
  data: {
    labels: xLabels,
    datasets: D.platforms.map(p => ({
      label:           p,
      data:            D.scores[p],
      borderColor:     D.colors[p],
      backgroundColor: D.colors[p] + '15',
      borderWidth:     2.5,
      pointRadius:     3,
      pointHoverRadius:6,
      tension:         0.35,
      spanGaps:        true,
    }))
  },
  options: { ...baseOpts(3.5, 5.1), plugins: { ...baseOpts(3.5,5.1).plugins } }
});

/* ── Per-platform cards ─────────────────────────────── */
const pgrid = document.getElementById('platform-grid');

D.platforms.forEach(p => {
  const color = D.colors[p];
  const k     = D.kpi[p];
  const dw    = k.delta_week;
  const dt    = k.delta_total;
  const nr    = D.newReviews[p];
  const id    = 'pc-' + p.toLowerCase().replace(/\s/g,'_');

  // Compute y range
  const vals   = D.scores[p].filter(v => v !== null);
  const yMin   = Math.max(1, parseFloat((Math.min(...vals) - 0.25).toFixed(1)));
  const yMax   = Math.min(5, parseFloat((Math.max(...vals) + 0.25).toFixed(1)));

  pgrid.insertAdjacentHTML('beforeend', `
    <div class="platform-card" style="--p-color:${color}">
      <div class="platform-card-header">
        <h3>${p}</h3>
        <div class="score-badge">${sc(k.current)} <span>/ 5</span></div>
      </div>
      <canvas id="${id}" height="130"></canvas>
      <div class="platform-stats">
        <div class="stat">
          <span class="s-val ${cls(dw)}">${dw!==0 ? sign(dw)+Math.abs(dw).toFixed(2) : '→ 0'}</span>
          <span class="s-lbl">Δ semana</span>
        </div>
        <div class="stat">
          <span class="s-val ${cls(dt)}">${dt!==0 ? sign(dt)+Math.abs(dt).toFixed(2) : '→ 0'}</span>
          <span class="s-lbl">Δ año</span>
        </div>
        <div class="stat">
          <span class="s-val">${nr > 0 ? '+'+nr : '—'}</span>
          <span class="s-lbl">Nuevas reseñas</span>
        </div>
        <div class="stat">
          <span class="s-val">${D.totalReviews[p] ?? '—'}</span>
          <span class="s-lbl">Total reseñas</span>
        </div>
      </div>
    </div>`);

  setTimeout(() => {
    new Chart(document.getElementById(id), {
      type: 'line',
      data: {
        labels: xLabels,
        datasets: [{
          label:           p,
          data:            D.scores[p],
          borderColor:     color,
          backgroundColor: color + '22',
          borderWidth:     2,
          pointRadius:     3,
          pointHoverRadius:5,
          tension:         0.35,
          fill:            true,
          spanGaps:        true,
        }]
      },
      options: {
        ...baseOpts(yMin, yMax),
        plugins: {
          legend: { display: false },
          tooltip: baseOpts(yMin,yMax).plugins.tooltip
        }
      }
    });
  }, 0);
});

/* ── Reviews helpers ────────────────────────────────── */
function stars(r) {
  const full = Math.round(r);
  return '★'.repeat(full) + '☆'.repeat(Math.max(0, 5 - full));
}
function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: 'short', year: 'numeric' });
}

function buildReviewSection(reviews, filtersId, gridId, showThreshold) {
  if (!reviews.length) return;
  const filtersEl = document.getElementById(filtersId);
  const gridEl    = document.getElementById(gridId);
  const sectionClass = 'rev-card-' + gridId;

  const plats = ['Todas', ...new Set(reviews.map(r => r.plataforma))];
  let activeFilter = 'Todas';

  plats.forEach(p => {
    const btn = document.createElement('button');
    btn.className = 'filter-btn' + (p === 'Todas' ? ' active' : '');
    btn.textContent = p;
    if (p !== 'Todas') btn.style.borderColor = D.colors[p] || '#444';
    btn.addEventListener('click', () => {
      activeFilter = p;
      filtersEl.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      gridEl.querySelectorAll('.review-card').forEach(card => {
        card.classList.toggle('hidden', activeFilter !== 'Todas' && card.dataset.plat !== activeFilter);
      });
    });
    filtersEl.appendChild(btn);
  });

  reviews.forEach(r => {
    const color = D.colors[r.plataforma] || '#888';
    const card = document.createElement('div');
    card.className = 'review-card';
    card.dataset.plat = r.plataforma;
    const footerExtra = showThreshold && r.threshold
      ? `<span style="color:var(--red)">★ ${r.rating.toFixed(1)}</span> <span style="color:var(--muted)">/ media ${r.threshold.toFixed(1)}</span>`
      : `<span style="color:#f0c040">${stars(r.rating)}</span> <span style="color:var(--muted)">${r.rating > 0 ? r.rating.toFixed(1) : '—'}</span>`;
    card.innerHTML = `
      <div class="review-header">
        <span class="plat-badge" style="--p-color:${color}">${r.plataforma}</span>
        <div class="review-meta">
          <span class="stars">${stars(r.rating)}</span>
          <span>${r.rating > 0 ? r.rating.toFixed(1) : '—'}</span>
          <span>·</span>
          <span>${fmtDate(r.fecha)}</span>
        </div>
      </div>
      ${r.titulo ? `<div class="review-title">${r.titulo}</div>` : ''}
      ${r.texto  ? `<div class="review-text">${r.texto}</div>`   : ''}
      <div class="review-footer">${r.usuario ? `<strong>${r.usuario}</strong> · ` : ''}${r.puesto || ''}${r.puesto ? ' · ' : ''}${footerExtra}</div>
    `;
    gridEl.appendChild(card);
  });
}

/* ── Reviews por debajo de la media ────────────────── */
buildReviewSection(D.recentReviews || [], 'reviews-filters', 'reviews-grid', true);

/* ── Últimas reviews (4 semanas, sin filtro rating) ── */
buildReviewSection(D.latestReviews || [], 'latest-filters', 'latest-grid', false);
</script>
</body>
</html>
"""


def generate(csv_path: Path = HISTORY_CSV, out_path: Path = DASHBOARD_HTML) -> Path:
    data = build_data(csv_path)
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False, indent=2))
    out_path.write_text(html, encoding="utf-8")
    print(f"  [Dashboard] {out_path.name} generado ({out_path.stat().st_size // 1024} KB)")
    return out_path


if __name__ == "__main__":
    generate()
    print("  Abri dashboard.html en tu browser.")
