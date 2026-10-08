@echo off
setlocal EnableExtensions
title Karamaniya - 30 runs, 18 months each

set "PROJECT_DIR=%USERPROFILE%\karamaniya"
if not exist "%PROJECT_DIR%\karamaniya\__main__.py" (
  echo Cannot find the Karamaniya project at "%PROJECT_DIR%".
  echo Edit PROJECT_DIR near the top of this file if the project is in another folder.
  pause
  exit /b 1
)
cd /d "%PROJECT_DIR%"

echo.
echo Choose Delegate D for this 30-run series:
echo   1. Local Ollama Qwen3.5 0.8B (default; no API key)
echo   2. OpenRouter stealth/space-bunny-alpha (requires an OpenRouter API key)
choice /c 12 /n /m "Select 1 or 2: "
if errorlevel 2 (
  set "COUNCIL_CONFIG=council.30runs-openrouter.toml"
  python -c "from karamaniya.envfile import load_env; import os,sys; load_env('.env'); sys.exit(0 if os.getenv('OPENROUTER_API_KEY') else 1)"
  if errorlevel 1 (
    echo.
    echo OPENROUTER_API_KEY is not set in the project .env or shell environment.
    echo Add the key in the Karamaniya control room, or rerun and choose option 1.
    pause
    exit /b 1
  )
) else (
  set "COUNCIL_CONFIG=council.30runs.toml"
)

echo.
echo Checking all five delegates. This sends one short test call to each.
python -m karamaniya check "%COUNCIL_CONFIG%"
if errorlevel 1 (
  echo.
  echo Delegate check failed. Fix the reported seat and run this file again.
  pause
  exit /b 1
)

echo.
echo Starting 30 sequential runs, 18 months each. Run data will be saved under:
echo   %PROJECT_DIR%\runs\batch-30x18-gpt6-luna
echo.
python -m karamaniya simulate "%COUNCIL_CONFIG%" --runs 30 --months 18 --first-seed 9000 --runs-dir "runs/batch-30x18-gpt6-luna" --prefix council --rotate-seats --no-check
if errorlevel 1 (
  echo.
  echo The batch stopped on an error or paused run. Completed runs remain saved.
  echo Review the last error and the Runs tab before starting any continuation.
  pause
  exit /b 1
)

echo.
echo All 30 runs completed. Open the Runs or Compare tab in Karamaniya to inspect them.
pause
endlocal
