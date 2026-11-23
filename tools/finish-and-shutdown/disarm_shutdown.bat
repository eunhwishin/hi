@echo off
chcp 65001 >nul
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
rem 종료 예약 취소
%PY% "%~dp0finish_and_shutdown.py" --disarm
echo.
pause
