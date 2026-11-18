#!/usr/bin/env python3
"""
Claude Code 작업 완료 시 자동 기록 · 저장 · 컴퓨터 종료 도구

Claude Code 의 Stop 훅으로 동작합니다.
- 평소에는 아무 일도 하지 않습니다 (Stop 훅은 매 응답마다 실행되기 때문).
- `on` 명령으로 "예약(arm)" 해 두면, 다음번 Claude 작업이 끝났을 때 한 번만:
    1) 작업 기록(마지막 응답 요약 + 대화 원본)을 로그 폴더에 저장
    2) 작업 폴더가 git 저장소면 변경사항을 자동 커밋 (옵션: push)
    3) N초 뒤 컴퓨터 종료 예약 (그 사이 `cancel` 로 취소 가능)

사용법:
    python auto_shutdown.py install          # ~/.claude/settings.json 에 Stop 훅 등록
    python auto_shutdown.py on [--delay 60] [--no-commit] [--push] [--dry-run]
    python auto_shutdown.py off              # 예약 해제
    python auto_shutdown.py status           # 현재 상태 확인
    python auto_shutdown.py cancel           # 이미 시작된 종료 카운트다운 취소
    python auto_shutdown.py uninstall        # 훅 제거
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
BASE_DIR = HOME / ".claude" / "auto-shutdown"
ARM_FILE = BASE_DIR / "armed.json"
PID_FILE = BASE_DIR / "shutdown.pid"
LOG_DIR = BASE_DIR / "logs"
SETTINGS_FILE = HOME / ".claude" / "settings.json"
SCRIPT_PATH = Path(__file__).resolve()
HOOK_MARKER = "auto_shutdown.py"
IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"


# ──────────────────────────── 유틸 ────────────────────────────
def now() -> dt.datetime:
    return dt.datetime.now()


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


# ──────────────────────────── 기록 ────────────────────────────
def last_assistant_text(transcript_path: str | None) -> str:
    """대화 기록(jsonl)에서 Claude 의 마지막 텍스트 응답을 꺼냅니다."""
    if not transcript_path or not Path(transcript_path).is_file():
        return ""
    last = ""
    with open(transcript_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("type") != "assistant":
                continue
            content = (entry.get("message") or {}).get("content")
            if isinstance(content, str):
                texts = [content]
            elif isinstance(content, list):
                texts = [c.get("text", "") for c in content
                         if isinstance(c, dict) and c.get("type") == "text"]
            else:
                texts = []
            joined = "\n".join(t for t in texts if t.strip())
            if joined:
                last = joined
    return last


def write_log(event: dict, git_result: str) -> Path:
    ts = now()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    day_log = LOG_DIR / f"{ts:%Y-%m-%d}.md"

    transcript = event.get("transcript_path")
    saved_transcript = ""
    if transcript and Path(transcript).is_file():
        dest = LOG_DIR / "transcripts" / f"{ts:%Y%m%d-%H%M%S}-{event.get('session_id', 'session')}.jsonl"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(transcript, dest)
        saved_transcript = str(dest)

    summary = last_assistant_text(transcript) or "(응답 내용을 찾지 못했습니다)"
    entry = (
        f"\n## {ts:%Y-%m-%d %H:%M:%S} 작업 완료\n\n"
        f"- 작업 폴더: `{event.get('cwd', '')}`\n"
        f"- 세션 ID: `{event.get('session_id', '')}`\n"
        f"- 대화 원본: `{saved_transcript or '없음'}`\n"
        f"- 저장(git): {git_result}\n\n"
        f"### Claude 마지막 응답\n\n{summary}\n"
    )
    with open(day_log, "a", encoding="utf-8") as f:
        f.write(entry)
    return day_log


# ──────────────────────────── 저장 (git) ────────────────────────────
def git_save(cwd: str | None, push: bool) -> str:
    if not cwd or not shutil.which("git"):
        return "건너뜀 (git 없음)"
    if run(["git", "rev-parse", "--is-inside-work-tree"], cwd).returncode != 0:
        return "건너뜀 (git 저장소 아님)"
    if not run(["git", "status", "--porcelain"], cwd).stdout.strip():
        return "변경사항 없음"
    run(["git", "add", "-A"], cwd)
    msg = f"auto-save: Claude Code 작업 완료 ({now():%Y-%m-%d %H:%M})"
    r = run(["git", "commit", "-m", msg], cwd)
    if r.returncode != 0:
        return f"커밋 실패: {(r.stderr or r.stdout).strip()[:200]}"
    result = "커밋 완료"
    if push:
        p = run(["git", "push"], cwd)
        result += ", push 완료" if p.returncode == 0 else f", push 실패: {p.stderr.strip()[:200]}"
    return result


# ──────────────────────────── 종료 ────────────────────────────
def schedule_shutdown(delay: int, dry_run: bool) -> str:
    if dry_run:
        return f"[dry-run] {delay}초 뒤 종료 예정이었음 (실제 종료 안 함)"
    if IS_WINDOWS:
        r = run(["shutdown", "/s", "/t", str(delay),
                 "/c", "Claude Code 작업 완료 - 자동 종료합니다. 취소: auto_shutdown.py cancel"])
        return "Windows 종료 예약됨" if r.returncode == 0 else f"종료 예약 실패: {r.stderr.strip()}"

    if IS_MAC:
        cmd = """osascript -e 'tell application "System Events" to shut down'"""
    else:
        cmd = "systemctl poweroff || loginctl poweroff || shutdown -h now"
    proc = subprocess.Popen(
        ["sh", "-c", f"sleep {delay} && ({cmd})"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    return f"{delay}초 뒤 종료 예약됨 (pid {proc.pid})"


def notify(title: str, message: str) -> None:
    """가능하면 바탕화면 알림을 띄웁니다 (실패해도 무시)."""
    try:
        if IS_MAC:
            run(["osascript", "-e", f'display notification "{message}" with title "{title}"'])
        elif not IS_WINDOWS and shutil.which("notify-send"):
            run(["notify-send", title, message])
        # Windows 는 shutdown /c 메시지로 알림이 표시됩니다.
    except Exception:
        pass


# ──────────────────────────── 명령 ────────────────────────────
def cmd_hook(_args) -> int:
    """Claude Code Stop 훅에서 호출됩니다."""
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        event = {}

    cfg = read_json(ARM_FILE)
    if not cfg:
        return 0  # 예약되지 않음 → 아무것도 안 함

    ARM_FILE.unlink(missing_ok=True)  # 1회용: 바로 해제
    git_result = git_save(event.get("cwd"), cfg.get("push", False)) if cfg.get("commit", True) else "건너뜀 (--no-commit)"
    log_path = write_log(event, git_result)
    shutdown_result = schedule_shutdown(int(cfg.get("delay", 60)), cfg.get("dry_run", False))

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"- 종료: {shutdown_result}\n")
    notify("Claude Code 자동 종료", f"기록 저장 완료. {shutdown_result}")
    # stderr 로 남기면 Claude Code 화면(verbose)에 표시됩니다.
    print(f"[auto-shutdown] 기록: {log_path} | 저장: {git_result} | {shutdown_result}", file=sys.stderr)
    return 0


def cmd_on(args) -> int:
    cfg = {
        "delay": args.delay,
        "commit": not args.no_commit,
        "push": args.push,
        "dry_run": args.dry_run,
        "armed_at": now().isoformat(timespec="seconds"),
    }
    write_json(ARM_FILE, cfg)
    if not is_installed():
        print("⚠️  아직 훅이 설치되지 않았습니다. 먼저 `install` 을 실행하세요.")
    print(f"✅ 예약됨: 다음 Claude 작업이 끝나면 기록·저장 후 {args.delay}초 뒤 종료합니다."
          + (" (dry-run)" if args.dry_run else ""))
    return 0


def cmd_off(_args) -> int:
    ARM_FILE.unlink(missing_ok=True)
    print("⏹  예약 해제됨.")
    return 0


def cmd_status(_args) -> int:
    print(f"훅 설치: {'예' if is_installed() else '아니오'}  ({SETTINGS_FILE})")
    cfg = read_json(ARM_FILE)
    print(f"종료 예약: {'예 ' + json.dumps(cfg, ensure_ascii=False) if cfg else '아니오'}")
    print(f"로그 폴더: {LOG_DIR}")
    return 0


def cmd_cancel(_args) -> int:
    ARM_FILE.unlink(missing_ok=True)
    if IS_WINDOWS:
        r = run(["shutdown", "/a"])
        print("🛑 종료 취소됨." if r.returncode == 0 else "진행 중인 종료가 없습니다.")
        return 0
    pid = PID_FILE.read_text().strip() if PID_FILE.exists() else ""
    if pid:
        try:
            os.killpg(int(pid), signal.SIGTERM)
            print("🛑 종료 취소됨.")
        except ProcessLookupError:
            print("진행 중인 종료가 없습니다.")
        PID_FILE.unlink(missing_ok=True)
    else:
        print("진행 중인 종료가 없습니다.")
    return 0


# ──────────────────────────── 설치 ────────────────────────────
def hook_command() -> str:
    return f'"{sys.executable}" "{SCRIPT_PATH}" hook'


def is_installed() -> bool:
    settings = read_json(SETTINGS_FILE, {}) or {}
    for group in settings.get("hooks", {}).get("Stop", []):
        for h in group.get("hooks", []):
            if HOOK_MARKER in h.get("command", ""):
                return True
    return False


def cmd_install(_args) -> int:
    settings = read_json(SETTINGS_FILE, {}) or {}
    if SETTINGS_FILE.exists():
        shutil.copy2(SETTINGS_FILE, SETTINGS_FILE.with_suffix(".json.bak"))
    stop = settings.setdefault("hooks", {}).setdefault("Stop", [])
    # 기존 등록 제거 후 다시 추가 (경로가 바뀌었을 수 있으므로)
    for group in stop:
        group["hooks"] = [h for h in group.get("hooks", []) if HOOK_MARKER not in h.get("command", "")]
    stop[:] = [g for g in stop if g.get("hooks")]
    stop.append({"hooks": [{"type": "command", "command": hook_command(), "timeout": 120}]})
    write_json(SETTINGS_FILE, settings)
    print(f"✅ Stop 훅 설치 완료: {SETTINGS_FILE}")
    print("   이제 `on` 명령으로 종료를 예약할 수 있습니다.")
    return 0


def cmd_uninstall(_args) -> int:
    settings = read_json(SETTINGS_FILE, {}) or {}
    stop = settings.get("hooks", {}).get("Stop", [])
    for group in stop:
        group["hooks"] = [h for h in group.get("hooks", []) if HOOK_MARKER not in h.get("command", "")]
    if "hooks" in settings:
        settings["hooks"]["Stop"] = [g for g in stop if g.get("hooks")]
        if not settings["hooks"]["Stop"]:
            del settings["hooks"]["Stop"]
    write_json(SETTINGS_FILE, settings)
    ARM_FILE.unlink(missing_ok=True)
    print("🗑  훅 제거 완료.")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(description="Claude Code 작업 완료 시 기록·저장·종료")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hook", help="(Claude Code 가 호출) Stop 훅 처리")
    on = sub.add_parser("on", help="다음 작업 완료 시 종료 예약")
    on.add_argument("--delay", type=int, default=60, help="종료까지 대기 시간(초), 기본 60")
    on.add_argument("--no-commit", action="store_true", help="git 자동 커밋 안 함")
    on.add_argument("--push", action="store_true", help="커밋 후 git push 도 실행")
    on.add_argument("--dry-run", action="store_true", help="실제로 끄지 않고 테스트만")
    sub.add_parser("off", help="예약 해제")
    sub.add_parser("status", help="상태 확인")
    sub.add_parser("cancel", help="진행 중인 종료 카운트다운 취소")
    sub.add_parser("install", help="Stop 훅 설치")
    sub.add_parser("uninstall", help="Stop 훅 제거")
    args = p.parse_args()

    return {
        "hook": cmd_hook, "on": cmd_on, "off": cmd_off, "status": cmd_status,
        "cancel": cmd_cancel, "install": cmd_install, "uninstall": cmd_uninstall,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
