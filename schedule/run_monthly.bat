@echo off
REM Wrapper the VBI-Monthly scheduled task calls (1st of each month).
REM Assembles the shot from cache, builds the report, emails it. Tees to a log.
setlocal
pushd "%~dp0\.."
set "VBI_ROOT=%CD%"
if not exist "%VBI_ROOT%\logs" mkdir "%VBI_ROOT%\logs"
set "STAMP=%DATE:/=-%_%TIME::=-%"
set "LOG=%VBI_ROOT%\logs\monthly_%STAMP: =0%.log"
set "PY=%VBI_ROOT%\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [task] venv python not found at %PY%>>"%LOG%"
  popd & exit /b 9
)

echo [task] %DATE% %TIME% VGR Brand Score monthly assemble>>"%LOG%"
"%PY%" -m vgr_brand_index.run_monthly %* 1>>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
>>"%LOG%" echo [task] finished rc=%RC%
popd
endlocal & exit /b %RC%
