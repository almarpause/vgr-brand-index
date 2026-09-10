@echo off
REM One-click push to GitHub (handles the cd /d + remote correctly).
REM Create an EMPTY repo named vgr-brand-index at github.com/almarpause first,
REM then run this. See WEB_DEPLOY.md for the one-time Pages setup.
cd /d "%~dp0"
echo Repo: %CD%
git remote remove origin 2>nul
git remote add origin https://github.com/almarpause/vgr-brand-index.git
git push -u origin master
echo.
echo Done. If a GitHub sign-in window appeared, approve it and re-run if needed.
pause
