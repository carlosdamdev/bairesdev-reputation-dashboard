#!/usr/bin/env python3
"""
BairesDev Individual Review Scraper
Scrapea reviews individuales de las 5 plataformas y las guarda en bairesdev_reviews.csv.

Uso:
    python reviews_scraper.py           # Solo Trustpilot (sin browser)
    python reviews_scraper.py --all     # Las 5 plataformas (abre Chrome)
"""

import csv, json, re, sys, datetime, subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")

import requests
from bs4 import BeautifulSoup

REVIEWS_CSV = Path(__file__).parent / "bairesdev_reviews.csv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

FIELDS = [
    "Plataforma", "Fecha_Review", "Semana_Review", "Año_Review",
    "Rating", "Usuario", "Puesto",
    "Titulo", "Texto", "Pros", "Contras",
    "Fecha_Scrape", "Semana_Scrape",
]

_CHALLENGE = ["just a moment", "security check", "blocked", "access denied",
              "verifying", "human verification", "un momento"]


@dataclass
class Review:
    plataforma:    str
    fecha_review:  str  = ""
    semana_review: Optional[int] = None
    año_review:    Optional[int] = None
    rating:        Optional[float] = None
    usuario:       str  = ""
    puesto:        str  = ""
    titulo:        str  = ""
    texto:         str  = ""
    pros:          str  = ""
    contras:       str  = ""
    fecha_scrape:  str  = field(default_factory=lambda: datetime.date.today().isoformat())
    semana_scrape: int  = field(default_factory=lambda: datetime.date.today().isocalendar()[1])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace("\n", " ").replace("\r", "")).strip()

def _date_to_week(d: str):
    try:
        iso = datetime.date.fromisoformat(d[:10]).isocalendar()
        return iso[1], iso[0]
    except Exception:
        return None, None

def _is_challenge(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _CHALLENGE)

def _wait_challenge(page, platform: str, max_sec=120):
    if not _is_challenge(page.title()):
        return True
    print(f"\n  [{platform}] Desafio detectado — resolvelo en Chrome. Esperando...", flush=True)
    for _ in range(max_sec):
        page.wait_for_timeout(1000)
        if not _is_challenge(page.title()):
            page.wait_for_timeout(3000)
            return True
    print(f"  [{platform}] Timeout de CAPTCHA — plataforma saltada.")
    return False


# ── Trustpilot ────────────────────────────────────────────────────────────────

def _parse_tp_html(html: str) -> tuple[list, int]:
    """Parsea HTML de una página de Trustpilot. Retorna (reviews, total_pages)."""
    reviews = []
    total_pages = 1
    soup = BeautifulSoup(html, "html.parser")

    script = soup.find("script", id="__NEXT_DATA__")
    if script and script.string:
        try:
            nd = json.loads(script.string)
            pp = nd.get("props", {}).get("pageProps", {})
            rev_list = pp.get("reviews", [])
            if rev_list:
                for r in rev_list:
                    cons = r.get("consumer", {}) or {}
                    dates = r.get("dates", {}) or {}
                    pub = (dates.get("publishedDate") or "")[:10]
                    wk, yr = _date_to_week(pub)
                    reviews.append(Review(
                        plataforma="Trustpilot",
                        fecha_review=pub, semana_review=wk, año_review=yr,
                        rating=float(r.get("rating") or r.get("stars") or 0),
                        usuario=_clean(cons.get("displayName") or "Anónimo"),
                        puesto=_clean(cons.get("title") or ""),
                        titulo=_clean(r.get("title") or ""),
                        texto=_clean(r.get("text") or ""),
                    ))
                total_pages = (pp.get("pagination") or {}).get("totalPages", 1)
                return reviews, total_pages
        except Exception:
            pass

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.string or "")
            for item in (obj if isinstance(obj, list) else [obj]):
                if item.get("@type") == "Review":
                    pub = (item.get("datePublished") or "")[:10]
                    wk, yr = _date_to_week(pub)
                    a = item.get("author") or {}
                    rv = (item.get("reviewRating") or {})
                    reviews.append(Review(
                        plataforma="Trustpilot",
                        fecha_review=pub, semana_review=wk, año_review=yr,
                        rating=float(rv.get("ratingValue") or 0),
                        usuario=_clean(a.get("name") if isinstance(a, dict) else a),
                        titulo=_clean(item.get("name") or ""),
                        texto=_clean(item.get("reviewBody") or ""),
                    ))
        except Exception:
            pass

    return reviews, total_pages


def scrape_trustpilot(page=None) -> list[Review]:
    reviews, page_num = [], 1
    print("  [Trustpilot] Reviews", end="", flush=True)

    while True:
        url = f"https://www.trustpilot.com/review/bairesdev.com?page={page_num}"
        html = None

        # Intentar con requests primero
        try:
            resp = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US"}, timeout=20)
            if resp.status_code == 200:
                html = resp.text
        except Exception:
            pass

        # Fallback a Playwright si requests fue bloqueado
        if html is None and page is not None:
            try:
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(2000)
                html = page.content()
            except Exception as e:
                print(f" error({e})")
                break

        if html is None:
            print(f" (bloqueado en pag {page_num})")
            break

        page_revs, total_pages = _parse_tp_html(html)
        reviews.extend(page_revs)
        print(f" ·{len(reviews)}", end="", flush=True)

        if not page_revs or page_num >= total_pages:
            break
        page_num += 1

    print(f" → {len(reviews)}")
    return reviews


# ── Clutch ────────────────────────────────────────────────────────────────────

def _parse_clutch_date(raw: str) -> str:
    """Convierte 'Apr 22, 2024' → '2024-04-22'."""
    raw = _clean(raw)
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            import datetime as _dt
            return _dt.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    return raw[:10]


def scrape_clutch(page) -> list[Review]:
    reviews = []
    print("  [Clutch] Reviews", end="", flush=True)
    page_num = 1

    try:
        page.goto("https://clutch.co/profile/bairesdev", timeout=35000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        if not _wait_challenge(page, "Clutch"):
            return reviews

        while True:
            soup = BeautifulSoup(page.content(), "html.parser")
            articles = soup.select("article.profile-review")
            if not articles:
                break

            for art in articles:
                try:
                    title_el  = art.select_one("h3")
                    rating_el = art.select_one(".sg-rating__number")
                    date_el   = art.select_one(".profile-review__date")
                    pos_el    = art.select_one(".reviewer_position")
                    name_el   = art.select_one(".reviewer_card--name")
                    quote_el  = art.select_one(".profile-review__quote p")
                    body_el   = art.select_one(".profile-review__summary, .profile-review__text")

                    if not rating_el:
                        continue
                    m = re.search(r"[\d.]+", rating_el.get_text())
                    if not m:
                        continue

                    pub = _parse_clutch_date(date_el.get_text() if date_el else "")
                    wk, yr = _date_to_week(pub)
                    reviews.append(Review(
                        plataforma="Clutch",
                        fecha_review=pub, semana_review=wk, año_review=yr,
                        rating=float(m.group()),
                        usuario=_clean(name_el.get_text() if name_el else ""),
                        puesto=_clean(pos_el.get_text() if pos_el else ""),
                        titulo=_clean(title_el.get_text() if title_el else ""),
                        texto=_clean((quote_el or body_el).get_text() if (quote_el or body_el) else ""),
                    ))
                except Exception:
                    continue

            print(f" ·{len(reviews)}", end="", flush=True)

            # Siguiente página
            next_btn = page.query_selector(
                "a.sg-pagination-v2-next:not(.sg-pagination-v2-disabled), "
                "a[aria-label='Next']:not([aria-disabled='true'])"
            )
            if not next_btn:
                break
            next_btn.click()
            page.wait_for_timeout(3000)
            page_num += 1
            if page_num > 20:
                break

    except Exception as e:
        print(f" error({e})", end="")

    print(f" → {len(reviews)}")
    return reviews


# ── Glassdoor ─────────────────────────────────────────────────────────────────

_GD_MONTHS_ES = {
    "ene": "01", "feb": "02", "mar": "03", "abr": "04",
    "may": "05", "jun": "06", "jul": "07", "ago": "08",
    "sep": "09", "oct": "10", "nov": "11", "dic": "12",
}

def _parse_gd_date(text: str) -> str:
    """Convierte '10 de abr de 2026' → '2026-04-10'."""
    text = text.strip().lower()
    m = re.match(r"(\d{1,2})\s+de\s+(\w{3})\w*\s+de\s+(\d{4})", text)
    if m:
        day, mon, yr = m.group(1), m.group(2)[:3], m.group(3)
        mm = _GD_MONTHS_ES.get(mon)
        if mm:
            return f"{yr}-{mm}-{int(day):02d}"
    # fallback: maybe already ISO
    m2 = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
    return m2.group(1) if m2 else ""


def _parse_glassdoor_soup(soup) -> list[dict]:
    results = []

    # Primary: current Glassdoor React structure (class names use CSS modules with hashes)
    cards = soup.find_all("article")
    for card in cards:
        try:
            # Rating — "3,0" with Spanish decimal separator
            rating = None
            el = card.select_one("[class*='ReviewRating_ratingLabel']") or \
                 card.select_one("[class*='ratingLabel']")
            if el:
                m = re.search(r"([\d]+)[,\.]([\d]+)", el.get_text())
                if m:
                    rating = float(f"{m.group(1)}.{m.group(2)}")
            if rating is None:
                continue

            # Fecha
            pub = ""
            el = card.select_one("[class*='Timestamp_reviewDate']") or \
                 card.select_one("[class*='reviewDate']")
            if el:
                pub = _parse_gd_date(el.get_text())

            # Título
            titulo = ""
            el = card.select_one("[class*='ContentTitle_link']") or \
                 card.select_one("h3[class*='heading_Heading']") or \
                 card.select_one("h3") or card.select_one("h2")
            if el:
                titulo = _clean(el.get_text())

            # Puesto
            puesto = ""
            el = card.select_one("[class*='ContentAvatarTags_avatarLabel']") or \
                 card.select_one("[class*='avatarLabel']")
            if el:
                puesto = _clean(el.get_text())

            # Pros / Contras via colored title paragraphs
            pros = contras = ""
            for p_title in card.select("p[class*='ReviewText_green'], p[class*='textTitle'][class*='green']"):
                sib = p_title.find_next_sibling()
                if sib:
                    pros = _clean(sib.get_text())
                    break
            for p_title in card.select("p[class*='ReviewText_red'], p[class*='textTitle'][class*='red']"):
                sib = p_title.find_next_sibling()
                if sib:
                    contras = _clean(sib.get_text())
                    break

            results.append(dict(
                fecha_review=pub, rating=rating,
                usuario="Anónimo", puesto=puesto,
                titulo=titulo, texto="", pros=pros, contras=contras,
            ))
        except Exception:
            continue

    if results:
        return results

    # Legacy JSON-LD fallback
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.string or "")
            for item in (obj if isinstance(obj, list) else [obj]):
                if item.get("@type") in ("Review", "EmployeeReview"):
                    pub = (item.get("datePublished") or "")[:10]
                    a  = item.get("author") or {}
                    rv = item.get("reviewRating") or {}
                    results.append(dict(
                        fecha_review=pub,
                        rating=float(rv.get("ratingValue") or 0),
                        usuario=_clean(a.get("name") if isinstance(a, dict) else "Anónimo"),
                        puesto=_clean(a.get("jobTitle", "") if isinstance(a, dict) else ""),
                        titulo=_clean(item.get("name") or ""),
                        texto=_clean(item.get("reviewBody") or ""),
                        pros="", contras="",
                    ))
        except Exception:
            pass

    return results


def scrape_glassdoor(page) -> list[Review]:
    reviews = []
    print("  [Glassdoor] Reviews", flush=True)
    base = "https://www.glassdoor.com.ar/Evaluaciones/BairesDev-Evaluaciones-E864485"
    page_num = 1

    while True:
        url = f"{base}.htm" if page_num == 1 else f"{base}_P{page_num}.htm"
        try:
            page.goto(url, timeout=35000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            if not _wait_challenge(page, "Glassdoor"):
                break

            # Scroll para cargar lazy content
            for _ in range(4):
                page.keyboard.press("End")
                page.wait_for_timeout(600)

            soup = BeautifulSoup(page.content(), "html.parser")
            page_revs = _parse_glassdoor_soup(soup)

            if not page_revs:
                print(f"  [Glassdoor] Pag {page_num}: 0 reviews — fin")
                break

            for r in page_revs:
                wk, yr = _date_to_week(r["fecha_review"])
                reviews.append(Review(
                    plataforma="Glassdoor",
                    fecha_review=r["fecha_review"], semana_review=wk, año_review=yr,
                    rating=r["rating"], usuario=r["usuario"], puesto=r["puesto"],
                    titulo=r["titulo"], texto=r["texto"],
                    pros=r["pros"], contras=r["contras"],
                ))

            print(f"  [Glassdoor] Pag {page_num}: {len(page_revs)} (total {len(reviews)})")

            # Siguiente página
            has_next = page.query_selector(
                "[aria-label='Next'], .nextButton, [data-test='pagination-next'], "
                "button:has-text('Next'), a[href*='_P" + str(page_num + 1) + "']"
            )
            if not has_next:
                break
            page_num += 1
            if page_num > 30:
                break

        except Exception as e:
            print(f"  [Glassdoor] Error pag {page_num}: {e}")
            break

    print(f"  [Glassdoor] Total: {len(reviews)}")
    return reviews


# ── TeamBlind ─────────────────────────────────────────────────────────────────

def _parse_teamblind_review_chunk(lines: list[str]) -> Optional[Review]:
    """Parsea una lista de lineas de una review de TeamBlind."""
    # Buscar rating en las primeras líneas
    rating = None
    rating_idx = -1
    for i, line in enumerate(lines[:5]):
        m = re.match(r"^([1-5]\.[0-9])$", line.strip())
        if m:
            rating = float(m.group(1))
            rating_idx = i
            break
    if rating is None:
        return None

    # Buscar employee line (Current/Former Employee ...)
    employee_line = ""
    emp_idx = -1
    for i, line in enumerate(lines):
        if re.search(r"(Current|Former)\s+Employee", line, re.I):
            employee_line = line
            emp_idx = i
            break

    # Buscar título (línea entre rating y employee que empiece con comillas)
    titulo = ""
    for line in lines[rating_idx + 1: emp_idx if emp_idx > 0 else len(lines)]:
        stripped = line.strip('""""  ')
        if len(stripped) > 5 and not re.match(r"^[1-5]\.[0-9]$", line) \
                and line.lower() not in ("popular", "recent", "helpful"):
            titulo = stripped
            break

    # Parsear employee_line: "Current Employee · x***** · Software Engineer · November 22 2024"
    puesto = ""
    pub = ""
    if employee_line:
        parts = [p.strip() for p in re.split(r"[·•\|ﾷ·]", employee_line)]
        for part in parts:
            m_date = re.match(r"([A-Za-z]+ \d{1,2} \d{4})", part)
            if m_date:
                try:
                    pub = datetime.datetime.strptime(m_date.group(1), "%B %d %Y").date().isoformat()
                except ValueError:
                    pass
            elif not re.search(r"(Current|Former)\s+Employee", part, re.I) \
                    and not re.match(r"[a-z]\*+$", part) and len(part) > 3:
                puesto = part

    # Extraer pros / cons / texto
    pros = contras = texto = ""
    try:
        idx_pros = next(i for i, l in enumerate(lines) if l.strip().lower() == "pros")
        idx_cons = next(i for i, l in enumerate(lines) if l.strip().lower() == "cons")
        pros    = " ".join(lines[idx_pros + 1:idx_cons])
        contras = " ".join(lines[idx_cons + 1:])
    except StopIteration:
        if emp_idx >= 0:
            texto = " ".join(lines[emp_idx + 1:])

    wk, yr = _date_to_week(pub)
    return Review(
        plataforma="TeamBlind",
        fecha_review=pub, semana_review=wk, año_review=yr,
        rating=rating, usuario="Anónimo", puesto=puesto,
        titulo=titulo, texto=texto, pros=pros, contras=contras,
    )


def _parse_teamblind_html(html: str) -> list[Review]:
    """TeamBlind embeds all reviews in one container; splits by 'Helpful (N)' markers."""
    soup = BeautifulSoup(html, "html.parser")
    reviews = []

    # Encontrar el contenedor con más de 6 h3 (tiene todos los reviews)
    container = None
    for div in soup.find_all("div"):
        if len(div.find_all("h3")) >= 6:
            container = div
            break
    if not container:
        return reviews

    raw = container.get_text(separator="\n", strip=True)
    chunks = re.split(r"Helpful\s*\(\d+\)", raw)

    for chunk in chunks:
        lines = [l.strip() for l in chunk.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        rev = _parse_teamblind_review_chunk(lines)
        if rev:
            reviews.append(rev)

    return reviews


def scrape_teamblind(page) -> list[Review]:
    reviews = []
    print("  [TeamBlind] Reviews", end="", flush=True)
    try:
        page.goto("https://www.teamblind.com/company/BairesDev/reviews",
                  timeout=35000, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        if not _wait_challenge(page, "TeamBlind"):
            return reviews

        for _ in range(20):
            page.keyboard.press("End")
            page.wait_for_timeout(600)

        reviews = _parse_teamblind_html(page.content())

    except Exception as e:
        print(f" error({e})", end="")

    print(f" → {len(reviews)}")
    return reviews


# ── Indeed ────────────────────────────────────────────────────────────────────

def scrape_indeed(page) -> list[Review]:
    reviews = []
    print("  [Indeed] Reviews", flush=True)
    start = 0

    while True:
        url = f"https://www.indeed.com/cmp/Bairesdev/reviews?fcountry=ALL&start={start}"
        try:
            page.goto(url, timeout=35000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            if not _wait_challenge(page, "Indeed"):
                break

            soup = BeautifulSoup(page.content(), "html.parser")
            page_count = 0

            # JSON-LD
            for tag in soup.find_all("script", type="application/ld+json"):
                try:
                    obj = json.loads(tag.string or "")
                    for item in (obj if isinstance(obj, list) else [obj]):
                        if item.get("@type") == "Review":
                            pub = (item.get("datePublished") or "")[:10]
                            wk, yr = _date_to_week(pub)
                            a  = item.get("author") or {}
                            rv = item.get("reviewRating") or {}
                            reviews.append(Review(
                                plataforma="Indeed",
                                fecha_review=pub, semana_review=wk, año_review=yr,
                                rating=float(rv.get("ratingValue") or 0),
                                usuario=_clean(a.get("name") if isinstance(a, dict) else "Anónimo"),
                                puesto=_clean(a.get("jobTitle", "") if isinstance(a, dict) else ""),
                                titulo=_clean(item.get("name") or ""),
                                texto=_clean(item.get("reviewBody") or ""),
                            ))
                            page_count += 1
                except Exception:
                    pass

            if not page_count:
                # CSS fallback
                card_sels = [
                    "[data-testid='review-container']",
                    "[class*='cmp-Review']",
                    "[itemtype*='Review']",
                    ".review",
                ]
                cards = []
                for sel in card_sels:
                    cards = soup.select(sel)
                    if cards:
                        break

                for card in cards:
                    try:
                        rating = None
                        for sel in ["[data-testid='overall-rating']","[class*='cmpOverallRating']",
                                    "[class*='ratingNumber']","[itemprop='ratingValue']"]:
                            el = card.select_one(sel)
                            if el:
                                m = re.search(r"[\d.]+", el.get_text())
                                if m:
                                    rating = float(m.group())
                                    break
                        if rating is None:
                            # aria-label fallback
                            for el in card.select("[aria-label]"):
                                m = re.search(r"([\d.]+)\s*out of\s*\d", el.get("aria-label",""), re.I)
                                if m:
                                    rating = float(m.group(1))
                                    break
                        if rating is None:
                            continue

                        puesto = ""
                        for sel in ["[data-testid='reviewer-job-title']","[class*='jobTitle']",
                                    "[class*='reviewerMetaData']"]:
                            el = card.select_one(sel)
                            if el:
                                puesto = _clean(el.get_text())
                                if puesto:
                                    break

                        pub = ""
                        for sel in ["[data-testid='review-date']","time","[class*='date']"]:
                            el = card.select_one(sel)
                            if el:
                                pub = (el.get("datetime", el.get_text().strip()))[:10]
                                break

                        titulo = ""
                        for sel in ["[data-testid='review-title']","h2 span","[class*='title']"]:
                            el = card.select_one(sel)
                            if el:
                                titulo = _clean(el.get_text())
                                if titulo:
                                    break

                        pros = contras = texto = ""
                        for el in card.select("p, [class*='reviewBody'], span[class*='text']"):
                            parent_cl = " ".join((el.find_parent().get("class") or [])).lower() \
                                        if el.find_parent() else ""
                            t = _clean(el.get_text())
                            if not t:
                                continue
                            if "pro" in parent_cl:
                                pros = t
                            elif "con" in parent_cl:
                                contras = t
                            elif not texto:
                                texto = t

                        wk, yr = _date_to_week(pub)
                        reviews.append(Review(
                            plataforma="Indeed",
                            fecha_review=pub, semana_review=wk, año_review=yr,
                            rating=rating, usuario="Anónimo", puesto=puesto,
                            titulo=titulo, texto=texto, pros=pros, contras=contras,
                        ))
                        page_count += 1
                    except Exception:
                        continue

            print(f"  [Indeed] start={start}: {page_count}", flush=True)
            if page_count < 18:
                break
            start += 20
            if start > 2000:
                break

        except Exception as e:
            print(f"  [Indeed] Error start={start}: {e}")
            break

    print(f"  [Indeed] Total: {len(reviews)}")
    return reviews


# ── CSV helpers ───────────────────────────────────────────────────────────────

def load_reviews(path: Path = REVIEWS_CSV) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save_reviews(new_revs: list[Review], path: Path = REVIEWS_CSV) -> int:
    existing = load_reviews(path)
    def _norm_rating(v):
        try:
            return str(round(float(v), 1))
        except (ValueError, TypeError):
            return str(v)

    seen = {(r["Plataforma"], r["Fecha_Review"], r["Usuario"], _norm_rating(r["Rating"]))
            for r in existing}

    write_header = not path.exists() or path.stat().st_size == 0
    added = 0
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            w.writeheader()
        for r in new_revs:
            key = (r.plataforma, r.fecha_review, r.usuario, _norm_rating(r.rating))
            if key not in seen:
                w.writerow({
                    "Plataforma":    r.plataforma,
                    "Fecha_Review":  r.fecha_review,
                    "Semana_Review": r.semana_review,
                    "Año_Review":    r.año_review,
                    "Rating":        r.rating,
                    "Usuario":       r.usuario,
                    "Puesto":        r.puesto,
                    "Titulo":        r.titulo,
                    "Texto":         r.texto,
                    "Pros":          r.pros,
                    "Contras":       r.contras,
                    "Fecha_Scrape":  r.fecha_scrape,
                    "Semana_Scrape": r.semana_scrape,
                })
                seen.add(key)
                added += 1

    total = len(existing) + added
    print(f"  [Reviews CSV] +{added} nuevas  (total {total})")
    return added


# ── Main ──────────────────────────────────────────────────────────────────────

CDP_PORT = 9222


def _cdp_available() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen(f"http://localhost:{CDP_PORT}/json/version", timeout=2)
        return True
    except Exception:
        return False


def _new_page(pw):
    """Lanza Chrome visible con anti-bot básico. Retorna (browser, page)."""
    browser = pw.chromium.launch(headless=False, channel="chrome")
    ctx = browser.new_context(
        user_agent=UA,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
    )
    ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return browser, ctx.new_page()


def _scrape_with_own_browser(pw, scrape_fn) -> list[Review]:
    """
    Usa el Chrome del usuario via CDP (abrir_chrome_debug.bat).
    Si CDP no esta disponible, avisa y saltea la plataforma.
    """
    if not _cdp_available():
        print("  [SALTADO] CDP no activo — cerrá Chrome y corré abrir_chrome_debug.bat primero.")
        return []

    browser = None
    page = None
    try:
        browser = pw.chromium.connect_over_cdp(f"http://localhost:{CDP_PORT}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        return scrape_fn(page)
    except Exception as e:
        print(f"  [browser error: {e}]")
        return []
    finally:
        try:
            if page:
                page.close()
        except Exception:
            pass


def run(all_platforms: bool = False):
    print("=" * 55)
    print("  BairesDev Review Scraper")
    print(f"  Fecha: {datetime.date.today()}")
    print(f"  Modo: {'todas las plataformas' if all_platforms else 'solo Trustpilot'}")
    print("=" * 55 + "\n")

    chrome_running = "chrome.exe" in subprocess.run(
        ["tasklist", "/fi", "imagename eq chrome.exe", "/nh"],
        capture_output=True, text=True
    ).stdout.lower()

    if all_platforms:
        if _cdp_available():
            print("  Modo: conectado a tu Chrome (CDP activo) — sin CAPTCHA.\n")
        else:
            print("  ATENCION: CDP no activo.")
            print("  Glassdoor/TeamBlind/Indeed seran saltados.")
            print("  Para scraping completo:")
            print("    1. Cerrar Chrome")
            print("    2. Correr abrir_chrome_debug.bat")
            print("    3. Correr este script de nuevo\n")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        # Trustpilot + Clutch comparten un browser headless-visible
        browser, p = _new_page(pw)
        try:
            save_reviews(scrape_trustpilot(page=p))
            if not all_platforms:
                return
            save_reviews(scrape_clutch(p))
        finally:
            try:
                browser.close()
            except Exception:
                pass

        # Cada plataforma manual en su propio browser para que cerrar uno no mate los demás
        save_reviews(_scrape_with_own_browser(pw, scrape_glassdoor))
        save_reviews(_scrape_with_own_browser(pw, scrape_teamblind))
        save_reviews(_scrape_with_own_browser(pw, scrape_indeed))


if __name__ == "__main__":
    run(all_platforms="--all" in sys.argv)
    print("\n  Listo.")
