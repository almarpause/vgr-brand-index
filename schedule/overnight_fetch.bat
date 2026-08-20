@echo off
REM One-time overnight staggered fetch (Reddit + Trends + GDELT) for the top brands.
REM Scheduled for ~22:15; the script itself hard-stops at 09:00. Tees to a log.
setlocal
pushd "%~dp0\.."
set "VBI_ROOT=%CD%"
if not exist "%VBI_ROOT%\logs" mkdir "%VBI_ROOT%\logs"
set "STAMP=%DATE:/=-%_%TIME::=-%"
set "LOG=%VBI_ROOT%\logs\overnight_%STAMP: =0%.log"
set "PY=%VBI_ROOT%\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [task] venv python not found at %PY%>>"%LOG%"
  popd & exit /b 9
)

echo [task] %DATE% %TIME% VGR Brand Index overnight fetch>>"%LOG%"
"%PY%" -m vgr_brand_index.overnight_fetch %* 1>>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
>>"%LOG%" echo [task] finished rc=%RC%
popd
endlocal & exit /b %RC%
