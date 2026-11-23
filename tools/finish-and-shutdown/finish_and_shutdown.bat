@echo off
chcp 65001 >nul
rem ------------------------------------------------------------------
rem  작업 마무리 후 종료 - 더블클릭 / 폴더를 이 파일 위에 끌어다 놓기
rem  폴더를 끌어다 놓으면 그 폴더를, 아니면 이 파일이 있는 폴더를 처리
rem  아래 OPTIONS 를 원하는 대로 바꾸세요 (설명은 README.md)
rem ------------------------------------------------------------------
set "OPTIONS=--delay 60"

set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=%CD%"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% "%~dp0finish_and_shutdown.py" "%TARGET%" %OPTIONS% %2 %3 %4 %5 %6 %7 %8 %9
echo.
pause
