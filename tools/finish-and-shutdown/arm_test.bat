@echo off
chcp 65001 >nul
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
rem 시험 예약: 컴퓨터는 끄지 않고 훅이 동작하는지만 확인
%PY% "%~dp0finish_and_shutdown.py" --arm --no-shutdown
echo.
pause
