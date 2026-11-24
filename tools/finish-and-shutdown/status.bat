@echo off
chcp 65001 >nul
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
rem 훅 등록/예약 상태와 최근 로그 보기
%PY% "%~dp0finish_and_shutdown.py" --status
echo.
pause
