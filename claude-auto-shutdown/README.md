# Claude Code 자동 기록 · 저장 · 종료

Claude Code 작업이 끝나면 **① 작업 기록 저장 → ② git 자동 커밋 → ③ 컴퓨터 종료**를 해 주는 도구입니다.
Claude Code의 **Stop 훅**으로 동작하며 Windows / macOS / Linux 모두 지원합니다. (Python 3.8+ 필요)

> Stop 훅은 Claude가 응답할 때마다 실행되므로, 이 도구는 **`on`으로 예약했을 때만 한 번** 동작합니다.
> 평소에는 아무 일도 하지 않으니 안심하고 설치해 두세요.

## 설치 (최초 1회)

```bash
python auto_shutdown.py install
```

`~/.claude/settings.json`에 Stop 훅이 등록됩니다. (기존 파일은 `settings.json.bak`으로 백업)
설치 후 Claude Code를 **재시작**하세요.

## 사용법

긴 작업을 맡기기 전에 다른 터미널에서:

```bash
python auto_shutdown.py on
```

→ 다음번 Claude 작업이 끝나면 기록·커밋 후 **60초 뒤 종료**합니다.

| 명령 | 설명 |
|---|---|
| `on --delay 300` | 종료까지 대기 시간(초) 지정 |
| `on --no-commit` | git 자동 커밋 안 함 |
| `on --push` | 커밋 후 `git push`까지 실행 |
| `on --dry-run` | 실제로 끄지 않고 테스트 (기록·커밋만) |
| `off` | 예약 해제 |
| `cancel` | 이미 시작된 종료 카운트다운 취소 |
| `status` | 설치/예약 상태 확인 |
| `uninstall` | 훅 제거 |

## 기록되는 내용

`~/.claude/auto-shutdown/logs/` 아래에 저장됩니다.

- `YYYY-MM-DD.md` — 날짜별 작업 기록 (작업 폴더, 세션 ID, git 결과, **Claude 마지막 응답**, 종료 결과)
- `transcripts/*.jsonl` — 대화 원본 전체 사본

## 처음엔 꼭 테스트부터

```bash
python auto_shutdown.py on --dry-run
```

Claude에게 아무 작업이나 시킨 뒤 로그 파일이 생기는지 확인하세요.

## 참고

- **Windows**: `shutdown /s /t N`을 사용합니다. 종료 알림창이 뜨고 `cancel`(= `shutdown /a`)로 취소할 수 있습니다.
- **macOS**: AppleScript로 종료합니다. 저장 안 된 앱이 있으면 종료가 멈출 수 있습니다.
- **Linux**: `systemctl poweroff`를 사용합니다. 권한이 없으면 sudo 설정이 필요할 수 있습니다.
- git 커밋은 Claude가 작업한 폴더가 git 저장소이고 변경사항이 있을 때만 실행됩니다.
