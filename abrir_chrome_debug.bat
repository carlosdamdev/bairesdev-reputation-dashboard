@echo off
echo ============================================================
echo  PASO 1: Cerrar Chrome si esta abierto (las cookies quedan
echo          guardadas — no perdes ninguna sesion iniciada).
echo  PASO 2: Este script reabre Chrome con tu sesion intacta.
echo  PASO 3: Corre el scraper: python reviews_scraper.py --all
echo ============================================================
echo.

tasklist /fi "imagename eq chrome.exe" /nh 2>nul | find "chrome.exe" >nul
if %errorlevel%==0 (
    echo ADVERTENCIA: Chrome sigue abierto.
    echo Cerralo primero y volvé a correr este bat.
    echo.
    pause
    exit /b 1
)

set CHROME=
for %%p in (
    "C:\Program Files\Google\Chrome\Application\chrome.exe"
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
) do if exist %%p set CHROME=%%p

if "%CHROME%"=="" (
    echo ERROR: No se encontro Chrome.
    pause
    exit /b 1
)

echo Abriendo Chrome con tu sesion...
start "" %CHROME% --remote-debugging-port=9222 ^
  "https://www.glassdoor.com.ar/Evaluaciones/BairesDev-Evaluaciones-E864485.htm" ^
  "https://www.teamblind.com/company/BairesDev/reviews" ^
  "https://www.indeed.com/cmp/Bairesdev/reviews?fcountry=ALL"

echo.
echo Chrome abierto. Esperando que cargue...
timeout /t 5 /nobreak >nul
echo Listo. Ya podes correr:  python reviews_scraper.py --all
