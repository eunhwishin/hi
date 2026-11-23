# finish-and-shutdown – 코딩이 끝나면 기록·저장·정리 후 컴퓨터 종료

작업 폴더를 지정하면 아래 순서로 마무리하고 컴퓨터를 끕니다.

| 단계 | 하는 일 |
|---|---|
| 0. 대기 *(선택)* | 폴더에 N분 동안 변경이 없거나(`--idle`), 지정한 프로그램이 끝날 때까지(`--wait-process`) 기다림 |
| 1. 정리 | `__pycache__`, `*.tmp`, `~$*`(오피스 임시), `Thumbs.db`, `.DS_Store` 등 찌꺼기와 빈 폴더 삭제 |
| 2. 기록 | 새로 만들거나 바뀐 파일 목록을 폴더 안 `WORKLOG.md` 에 날짜별로 추가 |
| 3. 저장 | git 저장소면 `git add` + `commit` (`--push` 주면 push 까지) |
| 4. 백업 *(선택)* | `--backup 폴더` 를 주면 작업 폴더 전체를 `폴더명_날짜시각.zip` 으로 보관 |
| 5. 종료 | 60초 카운트다운 후 컴퓨터 종료 – **Ctrl+C 로 취소** |

- 기록·정리·저장·백업 중 하나라도 실패하면 **컴퓨터를 끄지 않습니다** (`--force` 로 무시 가능).
- 찌꺼기가 기록·커밋되지 않도록 정리를 가장 먼저 합니다.
- `.git`, `node_modules`, `.venv` 폴더는 건드리지 않습니다. `*.bak` 은 기본으로 지우지 않습니다 (FixHYFont 백업 보호).

## ★ Claude Code 작업이 끝나면 자동으로 저장 후 종료하기

Claude Code 의 **Stop 훅**(Claude 가 응답을 끝낼 때 실행되는 명령)에 연결합니다.
평소에는 아무 일도 하지 않고, **종료 예약을 켠 경우에만 한 번** 실행됩니다.

1. **훅 등록 (처음 한 번)**: `install_hook.bat` 더블클릭
   - `%USERPROFILE%\.claude\settings.json` 에 Stop 훅이 추가됩니다 (기존 설정은 `.bak_날짜` 로 백업).
   - 이미 실행 중인 Claude Code 에서는 `/hooks` 를 한 번 열어 확인하거나 Claude Code 를 다시 시작해야 적용될 수 있습니다.
2. **종료 예약**: 자리를 비우기 전에 `arm_shutdown.bat` 더블클릭
   - Claude 가 작업을 끝내는 순간 → 새 창에서 정리·기록·커밋 → 120초 카운트다운 → 컴퓨터 종료
   - 작업 폴더는 Claude Code 가 작업 중인 폴더가 자동으로 쓰입니다.
3. **예약 취소**: `disarm_shutdown.bat` 더블클릭

명령줄로 하려면:
```bat
python finish_and_shutdown.py --install-hook
python finish_and_shutdown.py --arm --delay 120 --backup D:\backup
python finish_and_shutdown.py --status
python finish_and_shutdown.py --disarm
python finish_and_shutdown.py --uninstall-hook
```

> ⚠ Stop 훅은 Claude 가 **질문하려고 멈출 때도** 실행됩니다. 예약을 켜 두었다면 Claude 에게
> "질문하지 말고 끝까지 진행해" 라고 미리 말해 두세요. 실수로 꺼질 것 같으면 카운트다운 창에서 **Ctrl+C**.
>
> 이 방식은 **내 컴퓨터에서 실행 중인 Claude Code**(터미널 `claude` 또는 데스크톱 앱의 로컬 세션)에서만 동작합니다.
> 웹(claude.ai/code)의 클라우드 세션은 내 컴퓨터를 끌 수 없습니다.

## 준비
Python 3.8 이상 (Windows: <https://www.python.org> 또는 `winget install Python.Python.3.12`). 추가 설치 패키지 없음.

## 사용법

**처음엔 꼭 `--dry-run` 으로 확인하세요** (아무것도 바꾸지 않고 할 일만 보여줌):
```bat
python finish_and_shutdown.py D:\work\myproj --dry-run
```

지금 바로 마무리하고 끄기:
```bat
python finish_and_shutdown.py D:\work\myproj -m "로그인 기능 완료"
```

10분 동안 파일 변경이 없으면 (코딩이 끝났다고 보고) 마무리 + zip 백업 + 종료:
```bat
python finish_and_shutdown.py D:\work\myproj --idle 10 --backup D:\backup
```

VS Code 를 닫으면 마무리 + push + 종료:
```bat
python finish_and_shutdown.py D:\work\myproj --wait-process Code.exe --push
```

끄지는 말고 마무리만:
```bat
python finish_and_shutdown.py D:\work\myproj --no-shutdown
```

**더블클릭**: `finish_and_shutdown.bat` 을 작업 폴더에 복사해 더블클릭하거나, 작업 폴더를 bat 파일 위로 끌어다 놓으세요.
기본 옵션은 bat 파일 안의 `set "OPTIONS=--delay 60"` 줄에서 바꿉니다.

## 옵션
| 옵션 | 설명 |
|---|---|
| `folder` | 작업 폴더 (기본: 현재 폴더) |
| `-m 메모` | 기록과 커밋 메시지에 남길 메모 |
| `--idle 분` | 이 시간 동안 폴더에 변경이 없으면 진행 |
| `--wait-process 이름` | 이 프로그램이 종료되면 진행 (예: `Code.exe`, `acad.exe`) |
| `--poll 초` | 대기 중 확인 간격 (기본 30) |
| `--since "2026-11-23 09:00"` | git 이 아닌 폴더에서 이 시각 이후 바뀐 파일을 기록 (기본: 오늘 0시) |
| `--clean 패턴` | 추가로 지울 파일 패턴, 여러 번 사용 가능 (예: `--clean *.bak --clean *.log`) |
| `--no-clean` / `--keep-empty` | 정리 단계 생략 / 빈 폴더는 남김 |
| `--push` | 커밋 후 `git push` |
| `--backup 폴더` | zip 백업 저장 위치 |
| `--delay 초` | 종료 전 카운트다운 (기본 60) |
| `--no-shutdown` | 컴퓨터는 끄지 않음 |
| `--force` | 실패한 단계가 있어도 종료 |
| `--dry-run` | 미리보기만 |

## 종료 명령
- Windows: `shutdown /s /t 0`
- macOS: System Events 로 종료
- Linux: `systemctl poweroff` (권한이 필요할 수 있음)
