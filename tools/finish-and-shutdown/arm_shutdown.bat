@echo off
chcp 65001 >nul
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
rem 종료 예약: Claude Code 가 작업을 끝내면 저장 후 컴퓨터 종료
rem 작업 폴더를 이 파일 위에 끌어다 놓으면 그 폴더, 그냥 더블클릭하면 Claude Code 작업 폴더
set "OPTIONS=--delay 120"
if "%~1"=="" (%PY% "%~dp0finish_and_shutdown.py" --arm %OPTIONS%) else (%PY% "%~dp0finish_and_shutdown.py" "%~1" --arm %OPTIONS%)
echo.
pause
