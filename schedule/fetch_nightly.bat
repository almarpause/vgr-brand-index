@echo off
REM Wrapper the VBI-FetchNightly scheduled task calls (nightly, ~02:30).
REM Fetches one staggered shard of brand signals into the cache. Tees to a log.
setlocal
pushd "%~dp0\.."
set "VBI_ROOT=%CD%"
if not exist "%VBI_ROOT%\logs" mkdir "%VBI_ROOT%\logs"
set "STAMP=%DATE:/=-%_%TIME::=-%"
set "LOG=%VBI_ROOT%\logs\nightly_%STAMP: =0%.log"
set "PY=%VBI_ROOT%\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [task] venv python not found at %PY%>>"%LOG%"
  popd ^& exit /b 9
)

echo [task] %DATE% %TIME% VGR Brand Index nightly fetch>>"%LOG%"
"%PY%" -m vgr_brand_index.fetch_nightly %* 1>>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo [task] finished rc=%RC%>>"%LOG%"
popd
endlocal ^& exit /b %RC%
