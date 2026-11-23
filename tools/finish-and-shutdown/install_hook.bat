@echo off
chcp 65001 >nul
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
rem Claude Code 에 Stop 훅 등록 (처음 한 번만)
%PY% "%~dp0finish_and_shutdown.py" --install-hook
echo.
pause
