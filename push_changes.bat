@echo off
setlocal

cd /d "%~dp0"

echo.
echo === GitHub CTO: push current changes ===
echo.

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo This folder is not a git repository.
  echo Run git init and add a remote first.
  pause
  exit /b 1
)

if exist ".env" (
  git check-ignore .env >nul 2>&1
  if errorlevel 1 (
    echo ERROR: .env is not ignored by git. Refusing to continue.
    pause
    exit /b 1
  )
)

git status --short --branch
echo.
git status --short
echo.

git diff --quiet
set HAS_TRACKED=%ERRORLEVEL%
git ls-files --others --exclude-standard --directory | findstr . >nul
set HAS_UNTRACKED=%ERRORLEVEL%

if "%HAS_TRACKED%"=="0" if not "%HAS_UNTRACKED%"=="0" (
  echo Nothing new to commit. Trying to push existing local commits...
  git push
  if errorlevel 1 (
    echo.
    echo Normal push failed. Trying to set upstream for current branch...
    for /f "tokens=*" %%b in ('git branch --show-current') do set BRANCH=%%b
    git push -u origin %BRANCH%
    if errorlevel 1 (
      pause
      exit /b 1
    )
  )
  echo.
  echo Push complete.
  pause
  exit /b 0
)

git add .
if errorlevel 1 (
  pause
  exit /b 1
)

git diff --cached --name-only | findstr /R /C:"^\.env$" >nul
if not errorlevel 1 (
  echo ERROR: .env was staged. Unstaging and aborting.
  git restore --staged .env
  pause
  exit /b 1
)

for /f "tokens=1-4 delims=/ " %%a in ("%date%") do set DATE_PART=%%d-%%b-%%c
for /f "tokens=1-2 delims=.:" %%a in ("%time%") do set TIME_PART=%%a%%b
set COMMIT_MSG=Update GitHub CTO app %DATE_PART% %TIME_PART%

git commit -m "%COMMIT_MSG%"
if errorlevel 1 (
  pause
  exit /b 1
)

git push
if errorlevel 1 (
  echo.
  echo Normal push failed. Trying to set upstream for current branch...
  for /f "tokens=*" %%b in ('git branch --show-current') do set BRANCH=%%b
  git push -u origin %BRANCH%
  if errorlevel 1 (
    pause
    exit /b 1
  )
)

echo.
echo Push complete.
pause
