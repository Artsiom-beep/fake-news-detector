@echo off
setlocal

cd /d "%~dp0"

if not defined FACTCHECK_AI_IMAGE_MODEL (
  set FACTCHECK_AI_IMAGE_MODEL=haywoodsloan/ai-image-detector-deploy
)

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m src.desktop_app %*
) else (
  python -m src.desktop_app %*
)

endlocal
