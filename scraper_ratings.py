#!/usr/bin/env python3
"""
BairesDev Rating Scraper
Extrae score general y cantidad de reviews de:
  Trustpilot, Clutch, Glassdoor, TeamBlind, Indeed

Uso:
    python scraper_ratings.py              # solo sitios automaticos
    python scraper_ratings.py --all        # todos los sitios (pausa para CAPTCHAs)

Requisitos:
    pip install playwright requests beautifulsoup4
    python -m playwright install firefox
"""

import csv
import json
import os
import re
import sys
import datetime
import urllib.request as _urllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
except ImportError:
    print("ERROR: ejecuta:  pip install playwright && python -m playwright install firefox")
    sys.exit(1)


# ── Configuracion ─────────────────────────────────────────────────────────────

UA_CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

SITES = {
    "Trustpilot": "https://www.trustpilot.com/review/bairesdev.com",
    "Clutch":     "https://clutch.co/profile/bairesdev#highlights",
    "Glassdoor":  "https://www.glassdoor.com/Overview/Working-at-BairesDev-EI_IE864485.11,20.htm",
    "TeamBlind":  "https://www.teamblind.com/company/BairesDev/reviews",
    "Indeed":     "https://www.indeed.com/cmp/Bairesdev/reviews?fcountry=ALL",
}

CDP_PORT        = 9222
SPREADSHEET_ID  = "1eVWO3OkJ5yP2hZqABRbrxyaDxKOl0g507ZvSr-FAFZw"
CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"
TOKEN_FILE       = Path(__file__).parent / "token.json"

# Sitios que funcionan sin interaccion humana
AUTO_SITES = ["Trustpilot", "Clutch"]
# Sitios que requieren resolver CAPTCHA manualmente
MANUAL_SITES = ["Glassdoor", "TeamBlind", "Indeed"]

_CHALLENGE_TITLES = [
    "just a moment", "human verification", "security check",
    "security | glassdoor", "blocked", "access denied", "verifying", "un momento",
]

SELECTORS = {
    "Trustpilot": (
        ["[data-rating-typography]", "[class*='ratingScore']", ".star-rating__score"],
        ["[data-reviews-count-typography]", "[class*='reviewCount']", "[class*='reviewsCount']"],
    ),
    "Clutch": (
        ["[class*='sg-rating__number']", "[class*='rating_number']", "[class*='ratingNumber']"],
        ["[class*='reviews_count']", "[class*='reviewsNumber']", "[class*='review-count']"],
    ),
    "Glassdoor": (
        ["[data-test='rating-info__rating']", "[class*='ratingValue']", "[class*='overallRating']",
         "[class*='RatingNumber']", "[class*='ratingNum']", "div[class*='Rating'] span",
         "[class*='rating__value']", "[class*='ratingContainer'] span"],
        ["[data-test='reviews-count']", "[class*='reviewsCount']", "a[href*='reviews'] span",
         "[class*='reviewCount']", "span[class*='count']"],
    ),
    "TeamBlind": (
        ["[class*='overallRating']", "[class*='ratingScore']", "[class*='companyRating']",
         "[class*='rating-score']", "[class*='overview_rating']", "[class*='average']",
         "span[class*='rating']", "div[class*='rating'] > span:first-child"],
        ["[class*='reviewCount']", "[class*='totalReview']", "[class*='numReviews']",
         "[class*='review-count']", "[class*='total_review']", "span[class*='count']"],
    ),
    "Indeed": (
        ["[data-testid='overall-rating']", "[class*='cmpOverallRating']", "[class*='ratingNumber']",
         "[class*='RatingNumber']", "[class*='overallRating']", "span[itemprop='ratingValue']"],
        ["[data-testid='review-count']", "[class*='reviewCount']", "[class*='ia-ReviewCount']",
         "[itemprop='reviewCount']", "span[class*='count']"],
    ),
}


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class RatingResult:
    platform: str
    score: Optional[float] = None
    review_count: Optional[int] = None
    method: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_agg(obj) -> tuple[Optional[float], Optional[int]]:
    if isinstance(obj, dict):
        if obj.get("@type") == "AggregateRating":
            rv = obj.get("ratingValue")
            rc = obj.get("reviewCount") or obj.get("ratingCount")
            try:
                return float(str(rv).replace(",", ".")), \
                       int(re.sub(r"[^\d]", "", str(rc))) if rc else None
            except (TypeError, ValueError):
                return None, None
        if "aggregateRating" in obj:
            r, c = _find_agg(obj["aggregateRating"])
            if r: return r, c
        for v in obj.values():
            if isinstance(v, (dict, list)):
                r, c = _find_agg(v)
                if r: return r, c
    elif isinstance(obj, list):
        for item in obj:
            r, c = _find_agg(item)
            if r: return r, c
    return None, None


def extract_json_ld(html: str) -> tuple[Optional[float], Optional[int]]:
    for tag in BeautifulSoup(html, "html.parser").find_all("script", type="application/ld+json"):
        try:
            r, c = _find_agg(json.loads(tag.string or ""))
            if r: return r, c
        except Exception:
            continue
    return None, None


def parse_score(text: str) -> Optional[float]:
    if not text: return None
    m = re.search(r"\d+[.,]\d+|\d+", text.replace(",", "."))
    return float(m.group()) if m else None


def parse_count(text: str) -> Optional[int]:
    if not text: return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def is_challenge(title: str) -> bool:
    return any(kw in title.lower() for kw in _CHALLENGE_TITLES)


def _first_match(page: Page, selectors: list) -> str:
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=500):
                text = el.inner_text().strip()
                if text: return text
        except Exception:
            continue
    return ""


def _find_count(src: str, page: Page, platform: str) -> Optional[int]:
    """Busca review count por multiples metodos."""
    # JSON-LD
    _, c = extract_json_ld(src)
    if c: return c
    # JSON-regex
    rc = re.search(r'"reviewCount"\s*:\s*"?(\d+)"?', src)
    if rc: return int(rc.group(1))
    rc = re.search(r'"ratingCount"\s*:\s*"?(\d+)"?', src)
    if rc: return int(rc.group(1))
    # CSS selectors
    if platform in SELECTORS:
        _, count_sels = SELECTORS[platform]
        c = parse_count(_first_match(page, count_sels))
        if c: return c
    # Text-regex
    try:
        text = page.inner_text("body")
    except Exception:
        text = ""
    m = re.search(r"([\d,]+)\s*(?:reviews?|calificaciones?|ratings?)", text, re.I)
    if m: return int(m.group(1).replace(",", ""))
    return None


def _extract_from_page(page: Page, platform: str) -> tuple[Optional[float], Optional[int], str]:
    src = page.content()

    r, c = extract_json_ld(src)
    if r:
        if c is None: c = _find_count(src, page, platform)
        return r, c, "JSON-LD"

    rv = re.search(r'"ratingValue"\s*:\s*"?([\d.]+)"?', src)
    if rv:
        c = _find_count(src, page, platform)
        return float(rv.group(1)), c, "JSON-regex"

    if platform in SELECTORS:
        score_sels, _ = SELECTORS[platform]
        r = parse_score(_first_match(page, score_sels))
        if r:
            c = _find_count(src, page, platform)
            return r, c, "CSS"

    # Text-regex fallback
    try:
        text = page.inner_text("body")
    except Exception:
        text = ""
    m_score = re.search(r"\b([1-4]\.[0-9]|5\.0)\s*(?:/\s*5|out of 5|★)", text)
    if not m_score:
        m_score = re.search(r"(?:Overall|Rating|Score)[^\d]{0,20}([1-4]\.[0-9]|5\.0)", text, re.I)
    if m_score:
        c = _find_count(src, page, platform)
        return float(m_score.group(1)), c, "text-regex"

    return None, None, "not found"


# ── Scraping ──────────────────────────────────────────────────────────────────

def scrape_trustpilot() -> RatingResult:
    try:
        resp = requests.get(SITES["Trustpilot"],
                            headers={"User-Agent": UA_CHROME, "Accept-Language": "en-US,en;q=0.9"},
                            timeout=15)
        resp.raise_for_status()
        r, c = extract_json_ld(resp.text)
        if r: return RatingResult("Trustpilot", r, c, "requests")
    except Exception:
        pass
    return RatingResult("Trustpilot", method="requests-blocked")


def _new_ctx(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(
        user_agent=UA_CHROME,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return ctx


def _chrome_exe_path() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return "chrome"


def _try_connect_cdp(pw):
    """Intenta conectarse al Chrome existente via CDP. Retorna (browser, True) o (None, False)."""
    try:
        _urllib.urlopen(f"http://localhost:{CDP_PORT}/json/version", timeout=2)
        browser = pw.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
        return browser, True
    except Exception:
        return None, False


def _chrome_running() -> bool:
    import subprocess
    out = subprocess.run(
        ["tasklist", "/fi", "imagename eq chrome.exe", "/nh"],
        capture_output=True, text=True
    ).stdout
    return "chrome.exe" in out.lower()


def _chrome_profile_dir() -> Optional[str]:
    path = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    return path if os.path.exists(path) else None


def scrape_site(browser_or_ctx, platform: str, interactive: bool, cdp_mode: bool = False) -> RatingResult:
    from playwright.sync_api import BrowserContext as _BC
    result = RatingResult(platform)

    if isinstance(browser_or_ctx, _BC):
        # Contexto persistente (perfil real del usuario)
        ctx = browser_or_ctx
        page = ctx.new_page()
        close_ctx = False
    elif cdp_mode:
        ctx = browser_or_ctx.contexts[0] if browser_or_ctx.contexts else browser_or_ctx.new_context()
        page = ctx.new_page()
        close_ctx = False
    else:
        ctx = _new_ctx(browser_or_ctx)
        page = ctx.new_page()
        close_ctx = True

    try:
        page.goto(SITES[platform], timeout=35000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        if is_challenge(page.title()):
            if not interactive:
                result.method = "blocked (usa --all)"
                return result

            # Modo interactivo: esperar hasta que el titulo deje de ser un desafio
            print(f"\n  [{platform}] Desafio detectado — resolvelo en Chrome. El script continua automaticamente.")
            for _ in range(120):   # hasta 2 minutos
                page.wait_for_timeout(1000)
                if not is_challenge(page.title()):
                    break
            else:
                result.method = "CAPTCHA timeout (2 min)"
                return result

            # Dar tiempo extra para que cargue el contenido
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                page.wait_for_timeout(3000)
            page.mouse.wheel(0, 500)
            page.wait_for_timeout(2000)

        r, c, method = _extract_from_page(page, platform)
        result.score, result.review_count, result.method = r, c, method

        # Fallback Clutch: cantidad en el titulo de la pagina
        if platform == "Clutch" and result.review_count is None:
            m = re.search(r"Reviews?\s*\((\d+)\)", page.title())
            if m: result.review_count = int(m.group(1))

        # Si no encontro datos completos, guardar HTML para debug
        if result.score is None or result.review_count is None:
            os.makedirs("debug_pages", exist_ok=True)
            debug_path = f"debug_pages/{platform.lower()}_loaded.html"
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(page.content())
            print(f"\n    (HTML guardado en {debug_path} para debug)", end="")

    except Exception as exc:
        result.method = f"error: {exc}"
    finally:
        page.close()
        if close_ctx:
            ctx.close()

    return result


# ── Google Sheets ─────────────────────────────────────────────────────────────

def _gspread_client():
    """Retorna un cliente gspread autenticado, o None si no está configurado."""
    try:
        import gspread
    except ImportError:
        print("\n  [Sheets] Instala gspread:  pip install gspread")
        return None

    if not CREDENTIALS_FILE.exists():
        print("\n  [Sheets] No se encontro credentials.json — para configurar:")
        print("    1. Ir a https://console.cloud.google.com/")
        print("    2. Crear proyecto → APIs y Servicios → Biblioteca → habilitar 'Google Sheets API'")
        print("    3. Credenciales → Crear credenciales → ID de cliente OAuth 2.0 → App de escritorio")
        print("    4. Descargar JSON y guardar como 'credentials.json' en esta carpeta")
        print("    (Solo se hace una vez — despues el script corre solo)")
        return None

    try:
        gc = gspread.oauth(
            credentials_filename=str(CREDENTIALS_FILE),
            authorized_user_filename=str(TOKEN_FILE),
        )
        return gc
    except Exception as exc:
        print(f"\n  [Sheets] Error de autenticacion: {exc}")
        return None


def _find_week_header(values) -> tuple[int, int]:
    """Retorna (row_idx, col_idx) de la celda que contiene 'Week' como encabezado de tabla.
    Busca en todas las columnas de cada fila."""
    for r_idx, row in enumerate(values):
        for c_idx, cell in enumerate(row):
            if str(cell).strip().lower() == "week":
                # Verificar que la siguiente celda sea "Score" (es la tabla correcta)
                if len(row) > c_idx + 1 and str(row[c_idx + 1]).strip().lower() == "score":
                    return r_idx, c_idx
    # Fallback: cualquier celda "Week"
    for r_idx, row in enumerate(values):
        for c_idx, cell in enumerate(row):
            if str(cell).strip().lower() == "week":
                return r_idx, c_idx
    return -1, -1


def _update_platform_tab(sheet, week: int, score: float, total_reviews: Optional[int]):
    """Inserta fila Week N en la tab de la plataforma y actualiza Total Reviews."""
    values = sheet.get_all_values()

    header_idx, col_offset = _find_week_header(values)
    if header_idx < 0:
        print(f"  [Sheets] Sin encabezado 'Week' en tab '{sheet.title}'")
        return

    # Columnas 1-indexed para gspread
    col_week  = col_offset + 1
    col_score = col_offset + 2
    col_new   = col_offset + 3

    # Calcular new_reviews comparando con el total anterior en la hoja
    prev_total = None
    for row in values:
        if row and "total reviews" in str(row[0]).lower() and "2026" not in str(row[0]).lower():
            try:
                prev_total = int(re.sub(r"[^\d]", "", str(row[1])))
            except ValueError:
                pass
            break

    new_reviews: object = "-"
    if total_reviews is not None and prev_total is not None:
        diff = total_reviews - prev_total
        if diff > 0:
            new_reviews = diff

    # ¿La semana ya existe?
    for i in range(header_idx + 1, len(values)):
        try:
            cell_val = values[i][col_offset] if col_offset < len(values[i]) else ""
            if int(cell_val) == week:
                sheet.update_cell(i + 1, col_score, score)
                sheet.update_cell(i + 1, col_new,   new_reviews)
                print(f"  [Sheets] {sheet.title}: Week {week} actualizada")
                return
        except (ValueError, IndexError):
            break

    # Insertar fila nueva debajo del encabezado
    insert_row = header_idx + 2   # 1-indexed
    new_row_data = [""] * col_offset + [week, score, new_reviews]
    sheet.insert_row(new_row_data, insert_row)
    print(f"  [Sheets] {sheet.title}: Week {week} insertada  (score={score}, new={new_reviews})")

    # Actualizar Total Reviews (siempre en col A)
    if total_reviews is not None:
        fresh = sheet.get_all_values()
        for i, row in enumerate(fresh):
            if row and "total reviews" in str(row[0]).lower() and "2026" not in str(row[0]).lower():
                sheet.update_cell(i + 1, 2, total_reviews)
                break


def _copy_col_format(spreadsheet, sheet_id: int, src_col: int, dst_col: int, n_rows: int):
    """Copia el formato de src_col a dst_col (indices 0-based) via Sheets API copyPaste."""
    try:
        spreadsheet.batch_update({"requests": [{
            "copyPaste": {
                "source":      {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": n_rows,
                                "startColumnIndex": src_col, "endColumnIndex": src_col + 1},
                "destination": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": n_rows,
                                "startColumnIndex": dst_col, "endColumnIndex": dst_col + 1},
                "pasteType": "PASTE_FORMAT",
                "pasteOrientation": "NORMAL",
            }
        }]})
    except Exception as exc:
        print(f"  [Sheets] Advertencia — no se pudo copiar formato de columna: {exc}")


def _update_report_tab(sheet, spreadsheet, week: int, results: list):
    """Agrega columna Week N en las tablas del Report 2026 y completa los scores."""
    scores_map = {r.platform: r.score for r in results if r.score is not None}
    values = sheet.get_all_values()
    batch: list = []
    cols_formatted: set = set()   # (sheet_id, col_0idx) ya formateadas

    for r_idx, row in enumerate(values):
        # Detectar filas de encabezado con columnas "Week X"
        week_cols: dict[int, int] = {}
        max_wk, max_col = -1, -1
        for c_idx, cell in enumerate(row):
            m = re.match(r"^Week (\d+)$", str(cell).strip())
            if m:
                wn = int(m.group(1))
                week_cols[wn] = c_idx
                if wn > max_wk:
                    max_wk, max_col = wn, c_idx

        if max_wk < 0:
            continue

        # Determinar columna de Week N (creando las que faltan si es necesario)
        sheet_id = sheet.id
        n_rows   = sheet.row_count

        # Buscar la última semana anterior con datos reales como fuente de formato.
        # Evita propagar el estilo vacío de semanas intermedias sin scrape.
        src_col = min(week_cols.values())  # fallback: primera semana (siempre bien formateada)
        found_src = False
        for wk_s in sorted(week_cols.keys(), reverse=True):
            if wk_s >= week:
                continue
            col_s = week_cols[wk_s]
            for dr in range(r_idx + 1, len(values)):
                dr_row = values[dr]
                l0 = str(dr_row[0]).strip() if dr_row else ""
                l1 = str(dr_row[1]).strip() if len(dr_row) > 1 else ""
                if not l0 and not l1:
                    break
                if col_s < len(dr_row) and str(dr_row[col_s]).strip():
                    src_col = col_s
                    found_src = True
                    break
            if found_src:
                break

        if week in week_cols:
            week_col = week_cols[week]
            # Copiar formato desde src_col a TODAS las columnas entre src y week_col
            # (repara semanas intermedias sin formato en una sola pasada)
            for fix_col in range(src_col + 1, week_col + 1):
                if (sheet_id, fix_col) not in cols_formatted:
                    _copy_col_format(spreadsheet, sheet_id, src_col, fix_col, n_rows)
                    cols_formatted.add((sheet_id, fix_col))
        else:
            for wk in range(max_wk + 1, week + 1):
                new_col_0 = max_col + (wk - max_wk)          # 0-indexed destino
                if (sheet_id, new_col_0) not in cols_formatted:
                    _copy_col_format(spreadsheet, sheet_id, src_col, new_col_0, n_rows)
                    cols_formatted.add((sheet_id, new_col_0))
                col_1idx = new_col_0 + 1                      # 1-indexed para gspread
                batch.append({"range": sheet.cell(r_idx + 1, col_1idx).address,
                               "values": [[f"Week {wk}"]]})
            week_col = max_col + (week - max_wk)

        target_col_1 = week_col + 1   # 1-indexed

        # Actualizar filas de plataformas debajo del encabezado.
        # Cubre dos formatos:
        #   "Platform | Score | val0 | val1 ..."  (tablas Client/Talent Reviews)
        #   "Platform | val0  | val1 | ..."        (tabla del gráfico, fila 33)
        for dr in range(r_idx + 1, len(values)):
            dr_row = values[dr]
            label0 = str(dr_row[0]).strip() if dr_row else ""
            label1 = str(dr_row[1]).strip() if len(dr_row) > 1 else ""

            if not label0 and not label1:
                break  # fin de tabla

            if label0 in scores_map:
                batch.append({"range": sheet.cell(dr + 1, target_col_1).address,
                               "values": [[scores_map[label0]]]})

    if batch:
        sheet.batch_update(batch)
        print(f"  [Sheets] Report 2026: Week {week} actualizado ({len(batch)} celdas)")
    else:
        print(f"  [Sheets] Report 2026: sin cambios detectados")


def update_google_sheet(results: list, week: int):
    gc = _gspread_client()
    if gc is None:
        return

    print(f"\n  Actualizando Google Sheet (Week {week})...")
    try:
        ss = gc.open_by_key(SPREADSHEET_ID)
    except Exception as exc:
        print(f"  [Sheets] No se pudo abrir el spreadsheet: {exc}")
        return

    for result in results:
        if result.score is None:
            continue
        try:
            ws = ss.worksheet(result.platform)
            _update_platform_tab(ws, week, result.score, result.review_count)
        except Exception as exc:
            print(f"  [Sheets] {result.platform}: {exc}")

    try:
        report_ws = ss.worksheet("Report 2026")
        _update_report_tab(report_ws, ss, week, results)
    except Exception as exc:
        print(f"  [Sheets] Report 2026: {exc}")


# ── CSV ───────────────────────────────────────────────────────────────────────

HISTORY_CSV = Path(__file__).parent / "bairesdev_history.csv"
HISTORY_FIELDS = ["Año", "Semana", "Fecha_Inicio_Semana", "Plataforma", "Score", "Nuevas_Resenas"]
HISTORY_YEAR   = 2026

def _week_to_monday(year: int, week_num: int) -> datetime.date:
    if week_num == 0:
        return datetime.date.fromisocalendar(year, 1, 1) - datetime.timedelta(weeks=1)
    return datetime.date.fromisocalendar(year, week_num, 1)


def export_history_csv():
    """Lee todos los tabs de plataforma en Sheets y regenera bairesdev_history.csv."""
    gc = _gspread_client()
    if gc is None:
        return
    try:
        ss = gc.open_by_key(SPREADSHEET_ID)
    except Exception as exc:
        print(f"  [History] No se pudo abrir el spreadsheet: {exc}")
        return

    rows = []
    for name in ["Trustpilot", "Clutch", "Glassdoor", "TeamBlind", "Indeed"]:
        try:
            ws = ss.worksheet(name)
            vals = ws.get_all_values()
        except Exception as exc:
            print(f"  [History] {name}: {exc}")
            continue

        header_row, col_w = -1, -1
        for r_idx, row in enumerate(vals):
            for c_idx, cell in enumerate(row):
                if str(cell).strip().lower() == "week":
                    header_row, col_w = r_idx, c_idx
                    break
            if header_row >= 0:
                break
        if header_row < 0:
            continue

        col_score, col_new = col_w + 1, col_w + 2
        seen = False
        for row in vals[header_row + 1:]:
            wk_raw = row[col_w] if col_w < len(row) else ""
            if not wk_raw.strip():
                if seen: break
                continue
            try:
                week_num = int(wk_raw.strip())
            except ValueError:
                if seen: break
                continue
            seen = True
            sc_raw = row[col_score] if col_score < len(row) else ""
            nw_raw = row[col_new]   if col_new   < len(row) else ""
            try:
                score = float(sc_raw.replace(",", "."))
            except (ValueError, AttributeError):
                score = None
            rows.append({
                "Año":                HISTORY_YEAR,
                "Semana":             week_num,
                "Fecha_Inicio_Semana": _week_to_monday(HISTORY_YEAR, week_num).strftime("%Y-%m-%d"),
                "Plataforma":         name,
                "Score":              score,
                "Nuevas_Resenas":     nw_raw.strip() if nw_raw.strip() else "-",
            })

    rows.sort(key=lambda x: (x["Semana"], x["Plataforma"]))
    with open(HISTORY_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  [History] {HISTORY_CSV.name} actualizado ({len(rows)} filas)")


def save_csv(results: list[RatingResult], path: str):
    today = datetime.date.today()
    week  = today.isocalendar()[1]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Fecha", "Semana del Año", "Plataforma", "Score", "Cantidad de Reviews"])
        for r in results:
            writer.writerow([
                today.strftime("%Y-%m-%d"), week, r.platform,
                r.score        if r.score        is not None else "N/A",
                r.review_count if r.review_count is not None else "N/A",
            ])


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    all_sites  = "--all" in sys.argv or "-a" in sys.argv
    today      = datetime.date.today()
    output     = f"bairesdev_ratings_{today.strftime('%Y%m%d')}.csv"

    print("=" * 55)
    print("  BairesDev Rating Scraper")
    print(f"  Fecha: {today}  |  Semana: {today.isocalendar()[1]}")
    if all_sites:
        print("  Modo: completo (Trustpilot + Clutch + CAPTCHA manual)")
    else:
        print("  Modo: automatico (Trustpilot + Clutch)")
        print("  Tip: usa --all para incluir Glassdoor, TeamBlind e Indeed")
    print("=" * 55)

    results: list[RatingResult] = []

    # Trustpilot via requests (sin browser)
    print(f"\n  [Trustpilot]", end=" ", flush=True)
    tp = scrape_trustpilot()
    if tp.score is None:
        # fallback a browser si requests fue bloqueado
        tp = None
    else:
        results.append(tp)
        print(f"Score={tp.score}  Reviews={tp.review_count}  ({tp.method})")

    # Sitios que necesitan browser
    browser_sites = (["Trustpilot"] if tp is None else []) + \
                    ["Clutch"] + \
                    (MANUAL_SITES if all_sites else [])

    # Sitios automaticos: Firefox headless (Trustpilot fallback + Clutch)
    auto_browser_sites  = [s for s in browser_sites if s not in MANUAL_SITES]
    manual_browser_sites = [s for s in browser_sites if s in MANUAL_SITES]

    if auto_browser_sites:
        with sync_playwright() as pw:
            browser = pw.firefox.launch(headless=True)
            for name in auto_browser_sites:
                print(f"\n  [{name}]", end=" ", flush=True)
                r = scrape_site(browser, name, interactive=False)
                results.append(r)
                s = f"{r.score:.1f}" if r.score is not None else "N/A"
                c = f"{r.review_count:,}" if r.review_count is not None else "N/A"
                print(f"Score={s}  Reviews={c}  ({r.method})")
            browser.close()

    # Sitios manuales: preferir perfil real de Chrome (login), sino Chrome nuevo
    if manual_browser_sites and all_sites:
        with sync_playwright() as pw:
            persistent_ctx = None
            browser = None
            cdp_mode = False

            profile_dir = _chrome_profile_dir()
            if profile_dir and not _chrome_running():
                # Chrome esta cerrado: podemos usar el perfil real con el login del usuario
                try:
                    print("\n  Abriendo Chrome con tu perfil y sesion logueada...")
                    persistent_ctx = pw.chromium.launch_persistent_context(
                        user_data_dir=profile_dir,
                        channel="chrome",
                        headless=False,
                        no_viewport=True,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    print("  Chrome abierto con tu sesion.")
                except Exception as e:
                    print(f"  No se pudo usar el perfil ({e}), abriendo Chrome nuevo...")

            if persistent_ctx is None:
                if _chrome_running():
                    print("\n  ATENCION: Chrome esta abierto.")
                    print("  Para usar tu sesion logueada (sin CAPTCHA):")
                    print("    1. Logueate en Glassdoor, TeamBlind e Indeed en Chrome")
                    print("    2. Cerra Chrome")
                    print("    3. Corre el script de nuevo")
                    print("  Continuando con Chrome nuevo (puede pedir CAPTCHA)...\n")
                browser = pw.chromium.launch(headless=False, channel="chrome")

            browser_or_ctx = persistent_ctx if persistent_ctx else browser
            for name in manual_browser_sites:
                print(f"\n  [{name}]", end=" ", flush=True)
                r = scrape_site(browser_or_ctx, name, interactive=True)
                results.append(r)
                s = f"{r.score:.1f}" if r.score is not None else "N/A"
                c = f"{r.review_count:,}" if r.review_count is not None else "N/A"
                print(f"Score={s}  Reviews={c}  ({r.method})")

            if persistent_ctx:
                persistent_ctx.close()
            elif browser:
                browser.close()

    save_csv(results, output)
    update_google_sheet(results, today.isocalendar()[1])
    export_history_csv()
    try:
        import generate_dashboard
        generate_dashboard.generate()
    except Exception as exc:
        print(f"  [Dashboard] {exc}")

    print("\n" + "=" * 55)
    print(f"  CSV guardado: {output}")
    print("=" * 55)
    print(f"  {'Plataforma':<14} {'Score':>7}  {'Reviews':>12}")
    print("-" * 55)
    for r in results:
        s = f"{r.score:.1f}" if r.score is not None else "N/A"
        c = f"{r.review_count:,}" if r.review_count is not None else "N/A"
        print(f"  {r.platform:<14} {s:>7}  {c:>12}")
    print("=" * 55)


if __name__ == "__main__":
    main()
