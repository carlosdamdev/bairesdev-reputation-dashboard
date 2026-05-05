#!/usr/bin/env python3
"""
BairesDev — Weekly Run
Ejecuta en orden: ratings → reviews → dashboard

Uso:
    python run_weekly.py

Prerequisito (una sola vez por sesión):
    1. Cerrar Chrome
    2. Doble clic en abrir_chrome_debug.bat   (abre Chrome con CDP en puerto 9222)
    3. Loguearte en Glassdoor dentro de esa ventana de Chrome
    4. Correr este script
"""

import datetime
import subprocess
import sys
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).parent
DASHBOARD = HERE / "index.html"


def _cdp_ok() -> bool:
    try:
        urllib.request.urlopen("http://localhost:9222/json/version", timeout=2)
        return True
    except Exception:
        return False


def _run(label: str, args: list[str]) -> bool:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    result = subprocess.run(
        [sys.executable] + args,
        cwd=HERE,
    )
    return result.returncode == 0


def main():
    print("\n" + "=" * 60)
    print("  BairesDev Weekly Run")
    print("=" * 60)

    # ── Verificar Chrome CDP ──────────────────────────────────
    if not _cdp_ok():
        print("""
  [ERROR] Chrome no está corriendo con el puerto de debugging.

  Pasos previos:
    1. Cerrar Chrome completamente
    2. Doble clic en:  abrir_chrome_debug.bat
    3. Loguearte en Glassdoor dentro de esa ventana
    4. Volver a correr:  python run_weekly.py
""")
        sys.exit(1)

    print("\n  Chrome CDP: OK")
    print("  Asegurate de estar logueado en Glassdoor en la ventana de Chrome.")
    input("  Presioná Enter cuando estés listo para empezar...")

    ok = True

    # ── 1. Ratings (+ Google Sheets + historia CSV) ───────────
    ok &= _run("PASO 1 / 3 — Ratings", ["scraper_ratings.py", "--all"])

    # ── 2. Reviews ────────────────────────────────────────────
    ok &= _run("PASO 2 / 3 — Reviews", ["reviews_scraper.py", "--all"])

    # ── 3. Dashboard (reconstruye con ratings + reviews nuevos)
    ok &= _run("PASO 3 / 3 — Dashboard", ["generate_dashboard.py"])

    # ── 4. Git commit + push ──────────────────────────────────
    if ok:
        _git_push()

    # ── Resultado final ───────────────────────────────────────
    print("\n" + "=" * 60)
    if ok:
        print("  Listo. Semana procesada correctamente.")
        print("  Dashboard público: https://carlosdamdev.github.io/bairesdev-reputation-dashboard/index.html")
        try:
            webbrowser.open(DASHBOARD.as_uri())
        except Exception:
            pass
    else:
        print("  Algún paso falló — revisá los mensajes de arriba.")
    print("=" * 60 + "\n")


def _git_push():
    print(f"\n{'='*60}")
    print("  PASO 4 / 4 — Publicando en GitHub")
    print(f"{'='*60}")
    week = datetime.date.today().isocalendar()[1]
    year = datetime.date.today().year
    msg  = f"Semana {week} / {year}"

    # Stage archivos de datos + dashboard
    files = (
        list(HERE.glob("bairesdev_ratings_*.csv")) +
        [HERE / "bairesdev_history.csv",
         HERE / "bairesdev_reviews.csv",
         HERE / "index.html"]
    )
    stage = subprocess.run(
        ["git", "add"] + [str(f) for f in files if f.exists()],
        cwd=HERE
    )
    if stage.returncode != 0:
        print("  [Git] Error en git add")
        return

    commit = subprocess.run(["git", "commit", "-m", msg], cwd=HERE)
    if commit.returncode != 0:
        print("  [Git] Sin cambios nuevos para commitear.")
        return

    push = subprocess.run(["git", "push"], cwd=HERE)
    if push.returncode == 0:
        print(f"  [Git] Publicado: {msg}")
    else:
        print("  [Git] Error en git push — verificá tu conexión o credenciales.")


if __name__ == "__main__":
    main()
