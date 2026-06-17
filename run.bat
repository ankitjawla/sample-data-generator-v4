@echo off
REM Sample Data Generator v4 (superset) - Windows launcher (double-click or run in cmd).
REM Creates .venv if missing (else reuses it), installs deps, then runs the app.
REM Optional first arg overrides the port.
setlocal
cd /d "%~dp0"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8504"

echo ==^> Sample Data Generator v4 (superset)

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo ERROR: Python 3 not found. Install from https://www.python.org/downloads/
  echo Make sure "Add python.exe to PATH" is ticked during install.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo ==^> Creating virtual environment (.venv)...
  %PY% -m venv .venv
)
set "VENV_PY=.venv\Scripts\python.exe"

echo ==^> Installing dependencies...
"%VENV_PY%" -m pip install --quiet --upgrade pip
"%VENV_PY%" -m pip install --quiet -r requirements.txt

if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
  > "%USERPROFILE%\.streamlit\credentials.toml" (echo [general]& echo email = "")
)

echo ==^> Starting at http://localhost:%PORT%  (press Ctrl+C to stop)
"%VENV_PY%" -m streamlit run app.py --server.port %PORT%
endlocal
