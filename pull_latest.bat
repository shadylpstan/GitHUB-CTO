@echo off
setlocal

cd /d "%~dp0"

echo.
echo === GitHub CTO: pull latest code ===
echo Repo: %CD%
echo.

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo ERROR: This folder is not a git repository.
  pause
  exit /b 1
)

for /f %%i in ('git status --porcelain') do set HAS_CHANGES=1
if defined HAS_CHANGES (
  echo Local changes detected. Stashing them before pull...
  git stash push -u -m "auto-stash-before-pull-latest"
  if errorlevel 1 (
    echo ERROR: Could not stash local changes. Pull stopped.
    pause
    exit /b 1
  )
  echo.
)

echo Pulling latest code from the current branch...
git pull --ff-only
if errorlevel 1 (
  echo.
  echo ERROR: Pull failed. If this branch has diverged, pull manually and resolve it.
  pause
  exit /b 1
)

echo.
echo Pull complete.
if defined HAS_CHANGES (
  echo Your previous local changes were saved in git stash.
  echo Use "git stash list" to see them, or "git stash pop" to restore them.
)
echo.
pause

endlocal
