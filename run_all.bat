@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist .venv ( python -m venv .venv )
call .venv\Scripts\activate.bat
echo Installing packages and running the evaluation. Progress is in run_log.txt
echo [0/2] Installing packages > run_log.txt
python -m pip install -q -r requirements.txt >> run_log.txt 2>&1 || goto :failed
if not exist .env copy .env.example .env >nul
echo [1/2] Running tests >> run_log.txt
python -m pytest -q >> run_log.txt 2>&1 || goto :failed
echo [2/2] Evaluating the agent >> run_log.txt
python -m eval.run_eval >> run_log.txt 2>&1 || goto :failed
echo FINISHED >> run_log.txt
echo Done. Results are in eval\results.md
pause
exit /b 0
:failed
echo FAILED >> run_log.txt
echo Something failed. See run_log.txt
pause
