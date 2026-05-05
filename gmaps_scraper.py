#!/usr/bin/env python3
"""
BairesDev Google Maps scraper.
Scrapes 4 office locations for overall scores and individual reviews.

Usage:
    python gmaps_scraper.py           # scrape live + update CSVs
    python gmaps_scraper.py --init    # init CSVs from Google Sheet history (first run only)
    python gmaps_scraper.py --all     # same as default (compatibility with run_weekly)
"""

import csv
import datetime
import re
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

try:
    from playwright.sync_api import sync_playwright, Page
except ImportError:
    print("ERROR: pip install playwright && python -m playwright install chromium")
    sys.exit(1)

HERE             = Path(__file__).parent
GMAPS_HISTORY    = HERE / "gmaps_history.csv"
GMAPS_REVIEWS    = HERE / "gmaps_reviews.csv"
CDP_PORT         = 9222
SPREADSHEET_ID   = "1eVWO3OkJ5yP2hZqABRbrxyaDxKOl0g507ZvSr-FAFZw"
CREDENTIALS_FILE = HERE / "credentials.json"
TOKEN_FILE       = HERE / "token.json"

LOCATIONS = [
    ("Washington DC",  "https://maps.app.goo.gl/ZqnwzTHfeBNkFuoE9"),
    ("Greensboro",     "https://maps.app.goo.gl/Vgv75qJQg72UBz8C8"),
    ("San Francisco",  "https://maps.app.goo.gl/TrWDf2tJxPjVEqSs5"),
    ("Barcelona",      "https://maps.app.goo.gl/ZJZHhGGtd7JvE21TA"),
]
LOC_NAMES   = [name for name, _ in LOCATIONS]
HIST_FIELDS = ["Semana", "Fecha_Inicio_Semana"] + [n.replace(" ", "_") for n in LOC_NAMES]
REV_FIELDS  = ["Nombre", "Rating", "Texto", "Ubicacion", "Fecha", "Semana_Review", "Año_Review"]


# ── Date helpers ──────────────────────────────────────────────────────────────

def _week_to_monday(year: int, week_num: int) -> datetime.date:
    if week_num == 0:
        return datetime.date.fromisocalendar(year, 1, 1) - datetime.timedelta(weeks=1)
    return datetime.date.fromisocalendar(year, week_num, 1)


def _parse_relative_date(text: str) -> str:
    """Convert 'X weeks ago', 'X months ago', etc. to ISO date (approximate)."""
    today = datetime.date.today()
    t = text.strip().lower()

    if re.search(r"just now|today|hoy|ahora", t):
        return today.isoformat()

    m = re.search(r"(\d+)\s+week", t)
    if m:
        return (today - datetime.timedelta(weeks=int(m.group(1)))).isoformat()
    if re.search(r"\ba\s+week\b|una semana", t):
        return (today - datetime.timedelta(weeks=1)).isoformat()

    m = re.search(r"(\d+)\s+month", t)
    if m:
        months = int(m.group(1))
        yr, mo = today.year, today.month - months
        while mo <= 0:
            mo += 12
            yr -= 1
        try:
            return today.replace(year=yr, month=mo).isoformat()
        except ValueError:
            return datetime.date(yr, mo, 28).isoformat()
    if re.search(r"\ba\s+month\b|un mes", t):
        yr, mo = today.year, today.month - 1
        if mo == 0:
            mo, yr = 12, yr - 1
        try:
            return today.replace(year=yr, month=mo).isoformat()
        except ValueError:
            return datetime.date(yr, mo, 28).isoformat()

    m = re.search(r"(\d+)\s+year", t)
    if m:
        try:
            return today.replace(year=today.year - int(m.group(1))).isoformat()
        except ValueError:
            return f"{today.year - int(m.group(1))}-02-28"
    if re.search(r"\ba\s+year\b|un año", t):
        try:
            return today.replace(year=today.year - 1).isoformat()
        except ValueError:
            return f"{today.year - 1}-02-28"

    m = re.search(r"(20\d{2})", t)
    if m:
        return f"{m.group(1)}-01-01"

    return ""


# ── CDP check ─────────────────────────────────────────────────────────────────

def _cdp_ok() -> bool:
    try:
        urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json/version", timeout=2)
        return True
    except Exception:
        return False


# ── Google Maps scraper ───────────────────────────────────────────────────────

def _dismiss_consent(page: Page):
    """Dismiss GDPR / cookie consent dialogs (relevant for Barcelona)."""
    consent_sels = [
        "button#L2AGLb",
        "button[aria-label*='Accept all']",
        "button[aria-label*='Aceptar']",
        "form[action*='consent'] button",
        "button.tHlp8d",
    ]
    for sel in consent_sels:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1500):
                btn.click(timeout=2000)
                page.wait_for_timeout(1500)
                return
        except Exception:
            continue


def _extract_rating(page: Page) -> float | None:
    """Extract overall rating from a Google Maps place page."""
    # Strategy 1: div.F7nice (main rating display)
    for sel in [
        "div.F7nice span[aria-hidden='true']",
        "div.F7nice > span:first-child",
        "span.ceNzKf",
        "[class*='fontDisplayLarge']",
    ]:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=800):
                txt = el.inner_text().strip().replace(",", ".")
                m = re.search(r"(\d+\.?\d*)", txt)
                if m:
                    v = float(m.group(1))
                    if 1.0 <= v <= 5.0:
                        return v
        except Exception:
            continue

    # Strategy 2: aria-label on rating container
    try:
        html = page.content()
        for pat in [
            r'aria-label="Rated ([\d.]+) out of 5',
            r'aria-label="([\d.,]+) star',
            r'aria-label="([\d.,]+) estrel',
        ]:
            m = re.search(pat, html)
            if m:
                v = float(m.group(1).replace(",", "."))
                if 1.0 <= v <= 5.0:
                    return v
    except Exception:
        pass

    # Strategy 3: text-regex fallback
    try:
        body = page.inner_text("body")
        m = re.search(r"\b([1-4]\.[0-9]|5\.0)\b(?:\s*\([\d,]+\s*(?:review|opinion|reseñ|avis)|\s*star|\s*★)", body, re.I)
        if m:
            return float(m.group(1))
    except Exception:
        pass

    return None


def _qt(locator, timeout: int = 80) -> str:
    """Quick inner_text with short timeout — never blocks on missing elements."""
    try:
        return locator.first.inner_text(timeout=timeout).strip()
    except Exception:
        return ""


def _qa(locator, attr: str, timeout: int = 80) -> str:
    """Quick get_attribute with short timeout."""
    try:
        return locator.first.get_attribute(attr, timeout=timeout) or ""
    except Exception:
        return ""


def _extract_reviews(page: Page, loc_name: str) -> list[dict]:
    """Extract review cards from the currently visible reviews panel."""
    reviews = []
    today = datetime.date.today()

    # Try to click into the reviews tab
    try:
        btn = page.locator(
            "button[aria-label*='reviews'], button[aria-label*='Reviews'], "
            "button[aria-label*='reseñas'], [data-tab-index='1']"
        ).first
        btn.click(timeout=2500)
        page.wait_for_timeout(2000)
    except Exception:
        pass

    # Scroll the reviews panel — Google Maps uses a scrollable div, not the window.
    # Try to find and scroll the inner panel container first; fall back to keyboard.
    # Find the scrollable reviews panel — try multiple known selectors
    panel_sels = [
        ".m6QErb[aria-label]",
        ".DxyBCb",
        "div[role='feed']",
        ".section-scrollbox",
        ".siAUzd-neVct-Q3DXx-BvBYQ",   # newer Maps panel
    ]
    panel = None
    for sel in panel_sels:
        try:
            el = page.locator(sel).first
            el.wait_for(timeout=800)
            panel = el
            break
        except Exception:
            continue

    # Iterative scroll: keep going until container count stabilises
    REVIEW_SELS = ["[data-review-id]", ".jftiEf", ".jJc9Ad"]
    prev_count = 0
    stable_rounds = 0
    for _ in range(20):                        # up to 20 scroll attempts
        if panel:
            try:
                panel.evaluate("el => el.scrollTop += 1500")
            except Exception:
                page.keyboard.press("End")
        else:
            page.mouse.wheel(200, 400, delta_y=1500)
        page.wait_for_timeout(600)

        count = 0
        for sel in REVIEW_SELS:
            count = page.locator(sel).count()
            if count:
                break
        if count == prev_count:
            stable_rounds += 1
            if stable_rounds >= 3:      # 3 rounds with no new reviews → done
                break
        else:
            stable_rounds = 0
        prev_count = count

    # Final container list
    containers = []
    for sel in REVIEW_SELS:
        containers = page.locator(sel).all()
        if containers:
            break

    for container in containers[:40]:
        try:
            rev: dict = {"Ubicacion": loc_name}

            # Reviewer name — try selectors without is_visible()
            for sel in [".d4r55", "[class*='WNxzHc']", ".DU9Pgb", ".TSUbDb"]:
                t = _qt(container.locator(sel))
                if t:
                    rev["Nombre"] = t
                    break
            rev.setdefault("Nombre", "")

            # Star rating — read aria-label directly
            for sel in ["span[role='img']", ".kvMYJc", "span.MW4etd"]:
                lbl = _qa(container.locator(sel), "aria-label")
                m = re.search(r"(\d+)\s*star", lbl, re.I)
                if not m:
                    m = re.search(r"(\d+)\s*estrel", lbl, re.I)
                if m:
                    rev["Rating"] = float(m.group(1))
                    break
            rev.setdefault("Rating", None)

            # Date
            for sel in [".rsqaWe", ".DU9Pgb span:last-child", ".dehysf"]:
                raw = _qt(container.locator(sel))
                if raw and not raw.isdigit() and len(raw) > 2:
                    rev["Fecha"] = _parse_relative_date(raw)
                    break
            rev.setdefault("Fecha", "")

            # Review text
            for sel in [".wiI7pd", ".MyEned span", ".Jtu6Td"]:
                t = _qt(container.locator(sel))
                if t:
                    rev["Texto"] = t[:500]
                    break
            rev.setdefault("Texto", "")

            if not rev["Rating"] and not rev["Nombre"]:
                continue

            if rev["Fecha"]:
                try:
                    d = datetime.date.fromisoformat(rev["Fecha"])
                    rev["Semana_Review"] = d.isocalendar()[1]
                    rev["Año_Review"] = d.year
                except Exception:
                    rev["Semana_Review"] = today.isocalendar()[1]
                    rev["Año_Review"] = today.year
            else:
                rev["Semana_Review"] = today.isocalendar()[1]
                rev["Año_Review"] = today.year

            reviews.append(rev)
        except Exception:
            continue

    return reviews


def scrape_location(page: Page, name: str, url: str) -> tuple:
    """Scrape one Google Maps location. Returns (score|None, reviews list)."""
    print(f"  [GMaps] {name}", end=" ", flush=True)

    try:
        page.goto(url, timeout=50000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        _dismiss_consent(page)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
    except Exception as e:
        print(f"  load error: {e}")
        return None, []

    score = _extract_rating(page)
    print(f"Score={score:.1f}" if score else "Score=N/A", end=" ", flush=True)

    reviews = _extract_reviews(page, name)
    print(f"Reviews={len(reviews)}")

    return score, reviews


# ── Google Sheets reader ──────────────────────────────────────────────────────

def _gspread_client():
    try:
        import gspread
    except ImportError:
        print("  [Sheets] pip install gspread")
        return None
    if not CREDENTIALS_FILE.exists():
        print("  [Sheets] No credentials.json found")
        return None
    try:
        return gspread.oauth(
            credentials_filename=str(CREDENTIALS_FILE),
            authorized_user_filename=str(TOKEN_FILE),
        )
    except Exception as e:
        print(f"  [Sheets] Auth error: {e}")
        return None


_MONTH_NAMES = {
    "january":"01","february":"02","march":"03","april":"04","may":"05","june":"06",
    "july":"07","august":"08","september":"09","october":"10","november":"11","december":"12",
    "enero":"01","febrero":"02","marzo":"03","abril":"04","mayo":"05","junio":"06",
    "julio":"07","agosto":"08","septiembre":"09","octubre":"10","noviembre":"11","diciembre":"12",
}


def _month_name_to_date(month_str: str) -> str:
    """Convert a bare month name like 'March' to the most recent ISO date for that month."""
    today = datetime.date.today()
    key = month_str.strip().lower()
    mm = _MONTH_NAMES.get(key)
    if not mm:
        return ""
    month_int = int(mm)
    year = today.year if month_int <= today.month else today.year - 1
    return f"{year}-{mm}-01"


def _read_sheet_history() -> list[dict]:
    """Read 'Google Maps' tab, return list of weekly score rows (weeks 0-16).
    Sheet structure (row 8, 0-indexed 7):
      col 1 = 'Week', col 4 = Washington DC Score, col 5 = Greensboro Score,
      col 6 = San Francisco Score, col 8 = Barcelona Score
    """
    gc = _gspread_client()
    if not gc:
        return []
    try:
        ss = gc.open_by_key(SPREADSHEET_ID)
        ws = ss.worksheet("Google Maps")
    except Exception as e:
        print(f"  [Sheets] Cannot open 'Google Maps' tab: {e}")
        return []

    values = ws.get_all_values()
    year = 2026

    # Header row: index 7 (sheet row 8)
    header_idx = 7
    header = values[header_idx] if len(values) > header_idx else []

    # Build location→column map from header
    loc_col: dict[str, int] = {}
    week_col: int | None = None
    for c_idx, cell in enumerate(header):
        cell_s = str(cell).strip().lower()
        if cell_s == "week":
            week_col = c_idx
        for loc in LOC_NAMES:
            # Match "Washington DC Score" → "Washington DC", etc.
            if loc.lower() in cell_s:
                loc_col[loc] = c_idx

    rows = []
    # Data rows: indices 8-24 (sheet rows 9-25), weeks 0-16
    for row_idx in range(8, 26):
        if row_idx >= len(values):
            break
        row = values[row_idx]
        if not any(str(c).strip() for c in row):
            continue

        # Parse week number from "Week X" format
        week_num: int | None = None
        if week_col is not None and week_col < len(row):
            cell_v = str(row[week_col]).strip()
            m = re.match(r"[Ww]eek\s*(\d+)", cell_v)
            if m:
                week_num = int(m.group(1))
            else:
                try:
                    week_num = int(cell_v)
                except (ValueError, TypeError):
                    pass
        if week_num is None:
            week_num = 16 - (row_idx - 8)  # fallback: rows 8-24 → weeks 16-0

        entry: dict = {
            "Semana": week_num,
            "Fecha_Inicio_Semana": _week_to_monday(year, week_num).strftime("%Y-%m-%d"),
        }
        for loc in LOC_NAMES:
            key = loc.replace(" ", "_")
            if loc in loc_col and loc_col[loc] < len(row):
                cell_v = str(row[loc_col[loc]]).strip().replace(",", ".")
                try:
                    entry[key] = float(cell_v) if cell_v else None
                except ValueError:
                    entry[key] = None
            else:
                entry[key] = None
        rows.append(entry)

    return rows


def _read_sheet_reviews() -> list[dict]:
    """Read reviews block from 'Google Maps' tab (rows 28-42).
    Sheet structure: col 0=empty, col 1=Name, col 2=Client Experience,
    col 3=Review text, col 4=Score, col 5=Location, col 6=Date
    """
    gc = _gspread_client()
    if not gc:
        return []
    try:
        ss = gc.open_by_key(SPREADSHEET_ID)
        ws = ss.worksheet("Google Maps")
    except Exception as e:
        print(f"  [Sheets] Cannot open 'Google Maps' tab: {e}")
        return []

    values = ws.get_all_values()
    today = datetime.date.today()

    # Locate reviews header (around row index 27)
    rev_start = 28  # default
    for i in range(25, min(len(values), 45)):
        row = values[i]
        h = " ".join(str(c).lower() for c in row[:8])
        if any(kw in h for kw in ["name", "nombre", "review", "score", "location"]):
            rev_start = i + 1
            break

    reviews = []
    for row in values[rev_start:rev_start + 30]:
        if not any(str(c).strip() for c in row[:8]):
            break
        # col 0=empty, 1=Name, 2=Client Exp, 3=Review, 4=Score, 5=Location, 6=Date
        nombre    = str(row[1]).strip() if len(row) > 1 else ""
        texto     = str(row[3]).strip() if len(row) > 3 else ""
        rat_raw   = str(row[4]).strip() if len(row) > 4 else ""
        ubicacion_raw = str(row[5]).strip() if len(row) > 5 else ""
        fecha_raw     = str(row[6]).strip() if len(row) > 6 else ""

        # Map sheet abbreviations to canonical location names; skip unknown locations
        _LOC_MAP = {
            "sf": "San Francisco", "san francisco": "San Francisco",
            "va": "Washington DC",  "washington dc": "Washington DC", "dc": "Washington DC",
            "greensboro": "Greensboro", "gso": "Greensboro",
            "barcelona": "Barcelona",   "bcn": "Barcelona",
        }
        ubicacion = _LOC_MAP.get(ubicacion_raw.lower(), "")
        if not ubicacion:
            continue  # skip reviews for locations outside our 4 offices

        try:
            rating = float(rat_raw.replace(",", "."))
        except (ValueError, TypeError):
            m = re.search(r"(\d+\.?\d*)", rat_raw)
            rating = float(m.group(1)) if m else None

        # Parse date — sheet has month names like "March", "August"
        fecha = ""
        if fecha_raw:
            m = re.search(r"(20\d{2}-\d{2}-\d{2})", fecha_raw)
            if m:
                fecha = m.group(1)
            elif fecha_raw.strip().lower() in _MONTH_NAMES:
                fecha = _month_name_to_date(fecha_raw)
            else:
                fecha = _parse_relative_date(fecha_raw)

        if fecha:
            try:
                d = datetime.date.fromisoformat(fecha)
                semana, año = d.isocalendar()[1], d.year
            except Exception:
                semana, año = today.isocalendar()[1], today.year
        else:
            semana, año = today.isocalendar()[1], today.year

        if nombre or (texto and texto != "-") or rating:
            reviews.append({
                "Nombre":        nombre,
                "Rating":        rating,
                "Texto":         texto if texto != "-" else "",
                "Ubicacion":     ubicacion,
                "Fecha":         fecha,
                "Semana_Review": semana,
                "Año_Review":    año,
            })

    return reviews


# ── CSV helpers ───────────────────────────────────────────────────────────────

def _load_history() -> list[dict]:
    if not GMAPS_HISTORY.exists():
        return []
    with open(GMAPS_HISTORY, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _save_history(rows: list[dict]):
    rows.sort(key=lambda r: int(r.get("Semana", 0)))
    with open(GMAPS_HISTORY, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=HIST_FIELDS)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in HIST_FIELDS})


def _load_reviews() -> list[dict]:
    if not GMAPS_REVIEWS.exists():
        return []
    with open(GMAPS_REVIEWS, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _save_reviews(rows: list[dict]):
    with open(GMAPS_REVIEWS, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=REV_FIELDS)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in REV_FIELDS})


def _upsert_week(week: int, scores: dict):
    """Insert or update the current week's scores in gmaps_history.csv."""
    today = datetime.date.today()
    rows = _load_history()
    fecha = _week_to_monday(today.year, week).strftime("%Y-%m-%d")

    for row in rows:
        try:
            if int(row["Semana"]) == week:
                for loc in LOC_NAMES:
                    key = loc.replace(" ", "_")
                    if scores.get(key) is not None:
                        row[key] = scores[key]
                _save_history(rows)
                return
        except (ValueError, TypeError):
            pass

    new_row: dict = {"Semana": week, "Fecha_Inicio_Semana": fecha}
    for loc in LOC_NAMES:
        key = loc.replace(" ", "_")
        new_row[key] = scores.get(key, "")
    rows.append(new_row)
    _save_history(rows)


def _merge_reviews(new_reviews: list[dict]):
    existing = _load_reviews()
    seen = {
        (r.get("Nombre", ""), (r.get("Texto") or "")[:50], r.get("Ubicacion", ""), str(r.get("Rating", "")))
        for r in existing
    }
    added = 0
    for rev in new_reviews:
        key = (rev.get("Nombre", ""), (rev.get("Texto") or "")[:50], rev.get("Ubicacion", ""), str(rev.get("Rating", "")))
        if key not in seen:
            existing.append(rev)
            seen.add(key)
            added += 1
    _save_reviews(existing)
    print(f"  [GMaps Reviews] +{added} nuevas (total {len(existing)})")


# ── Init from Google Sheet ────────────────────────────────────────────────────

def init_from_sheet():
    """Seed CSVs from historical Google Sheet data (one-time operation)."""
    print("  Leyendo historial de Google Sheet (pestaña Google Maps)...")

    hist = _read_sheet_history()
    if hist:
        _save_history(hist)
        print(f"  [GMaps History] {GMAPS_HISTORY.name} creado ({len(hist)} semanas)")
    else:
        print("  [GMaps History] Sin datos encontrados en Google Sheet")

    revs = _read_sheet_reviews()
    if revs:
        _save_reviews(revs)
        print(f"  [GMaps Reviews] {GMAPS_REVIEWS.name} creado ({len(revs)} reviews)")
    else:
        print("  [GMaps Reviews] Sin reviews encontradas en Google Sheet")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    init_mode = "--init" in sys.argv
    today = datetime.date.today()
    week  = today.isocalendar()[1]

    print("=" * 55)
    print("  BairesDev Google Maps Scraper")
    print(f"  Fecha: {today}  |  Semana: {week}")
    print("=" * 55)

    if init_mode:
        init_from_sheet()
        return

    # Auto-seed from sheet if history doesn't exist yet
    if not GMAPS_HISTORY.exists():
        print("  gmaps_history.csv no encontrado — inicializando desde Google Sheet...")
        init_from_sheet()

    if not _cdp_ok():
        print("  [GMaps] Chrome CDP no activo — salteando scrape de Google Maps.")
        return

    print("  Modo: conectado a Chrome (CDP activo)\n")

    scores: dict = {loc.replace(" ", "_"): None for loc in LOC_NAMES}
    all_reviews: list[dict] = []

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        except Exception as e:
            print(f"  [GMaps] Error conectando a Chrome CDP: {e}")
            return

        for loc_name, url in LOCATIONS:
            page = ctx.new_page()
            try:
                score, reviews = scrape_location(page, loc_name, url)
                scores[loc_name.replace(" ", "_")] = score
                all_reviews.extend(reviews)
            finally:
                page.close()

    _upsert_week(week, scores)
    _merge_reviews(all_reviews)

    print(f"\n  Semana {week} actualizada.")
    for loc, _ in LOCATIONS:
        key = loc.replace(" ", "_")
        v = scores[key]
        print(f"    {loc:<16} {v:.1f}" if v else f"    {loc:<16} N/A")


if __name__ == "__main__":
    main()
