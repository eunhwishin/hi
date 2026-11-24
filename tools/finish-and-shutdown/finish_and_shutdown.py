#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
finish_and_shutdown.py - 코딩이 끝나면 기록 → 정리 → 저장 → 백업 → 컴퓨터 종료

순서
  0. 대기   : (선택) 폴더에 변경이 N분 동안 없거나, 지정한 프로그램이 끝날 때까지 기다림
  1. 정리   : 임시/찌꺼기 파일(__pycache__, *.tmp, ~$*, Thumbs.db ...)과 빈 폴더 삭제
  2. 기록   : 새로 만들거나 바뀐 파일 목록을 WORKLOG.md 에 추가
  3. 저장   : git 저장소면 git add + commit (선택: push)
  4. 백업   : (선택) 폴더 전체를 zip 으로 압축해 백업 폴더에 보관
  5. 종료   : 카운트다운 후 컴퓨터 종료 (Ctrl+C 로 취소)

중간 단계에서 오류가 나면 컴퓨터를 끄지 않습니다 (--force 로 무시 가능).
표준 라이브러리만 사용하므로 Python 3.8+ 만 있으면 됩니다.
"""
import argparse
import datetime as dt
import fnmatch
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 정리할 때 지울 파일/폴더 이름 패턴 (필요하면 --clean 으로 추가)
JUNK_FILES = ["*.pyc", "*.pyo", "*.tmp", "*.temp", "~$*", ".~lock.*",
              "Thumbs.db", "desktop.ini", ".DS_Store", "*.swp", "*.swo"]
JUNK_DIRS = ["__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
             ".ipynb_checkpoints"]
# 절대 건드리지 않는 폴더
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv"}

LOG_NAME = "WORKLOG.md"
CLAUDE_DIR = Path.home() / ".claude"
ARM_FILE = CLAUDE_DIR / "finish_and_shutdown.armed.json"   # 종료 예약 표시 파일
HOOK_LOG = CLAUDE_DIR / "finish_and_shutdown.log"
HOOK_MARK = "finish_and_shutdown.py"


class StepError(Exception):
    pass


def say(msg=""):
    print(msg, flush=True)


def now():
    return dt.datetime.now()


# ----------------------------------------------------------------- 공통 도구
def walk(root: Path):
    """SKIP_DIRS 를 제외하고 (폴더, 하위폴더목록, 파일목록) 을 돌려준다."""
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        yield Path(cur), dirs, files


def latest_mtime(root: Path, ignore: set) -> float:
    latest = 0.0
    for cur, _dirs, files in walk(root):
        for f in files:
            p = cur / f
            if p.resolve() in ignore:
                continue
            try:
                latest = max(latest, p.stat().st_mtime)
            except OSError:
                pass
    return latest


def is_git_repo(root: Path) -> bool:
    return shutil.which("git") is not None and run_git(root, "rev-parse", "--is-inside-work-tree", check=False).strip() == "true"


def run_git(root: Path, *args, check=True) -> str:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise StepError(f"git {' '.join(args)} 실패:\n{r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def process_running(name: str) -> bool:
    name_l = name.lower()
    try:
        if platform.system() == "Windows":
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                                 text=True, errors="replace").stdout
            names = [line.split('","')[0].strip('"').lower() for line in out.splitlines() if line]
            return any(n == name_l or n == name_l + ".exe" for n in names)
        out = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True,
                             text=True, errors="replace").stdout
        return any(Path(line.strip()).name.lower() == name_l for line in out.splitlines())
    except FileNotFoundError:
        raise StepError("프로세스 목록을 읽을 수 없습니다 (tasklist/ps 없음).")


# ----------------------------------------------------------------- 0. 대기
def step_wait(args, root: Path, ignore: set):
    if args.wait_process:
        say(f"[대기] '{args.wait_process}' 프로그램이 끝나기를 기다립니다... (Ctrl+C 로 중단)")
        if not process_running(args.wait_process):
            say(f"  ※ 지금 '{args.wait_process}' 가 실행 중이 아닙니다. 바로 진행합니다.")
        while process_running(args.wait_process):
            time.sleep(args.poll)
        say(f"  '{args.wait_process}' 종료 확인.")

    if args.idle:
        limit = args.idle * 60
        say(f"[대기] 폴더에 {args.idle:g}분 동안 변경이 없으면 진행합니다... (Ctrl+C 로 중단)")
        while True:
            quiet = time.time() - latest_mtime(root, ignore)
            if quiet >= limit:
                break
            left = int(limit - quiet)
            say(f"  마지막 변경 후 {int(quiet)}초 경과 (남은 시간 약 {left}초)")
            time.sleep(min(args.poll, max(1, left)))
        say("  작업이 끝난 것으로 판단했습니다.")


# ----------------------------------------------------------------- 1. 기록
def collect_changes(root: Path, since: dt.datetime, git: bool, ignore: set):
    """[(상태, 상대경로)] 목록"""
    changes = []
    if git:
        out = run_git(root, "status", "--porcelain", "-uall", "--", ".")
        top = Path(run_git(root, "rev-parse", "--show-toplevel").strip())
        labels = {"??": "새 파일", "A": "추가", "M": "수정", "D": "삭제", "R": "이름변경"}
        for line in out.splitlines():
            code, path = line[:2], line[3:].strip().strip('"')
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            full = (top / path).resolve()
            if full in ignore:
                continue
            key = "??" if code == "??" else code.strip()[:1]
            try:
                rel = full.relative_to(root.resolve())
            except ValueError:
                rel = Path(path)
            changes.append((labels.get(key, code.strip()), rel.as_posix()))
    else:
        ts = since.timestamp()
        for cur, _dirs, files in walk(root):
            for f in files:
                p = cur / f
                if p.resolve() in ignore:
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                if st.st_mtime >= ts:
                    created = getattr(st, "st_birthtime", st.st_ctime if os.name == "nt" else None)
                    kind = "새 파일" if created and created >= ts else "수정"
                    changes.append((kind, p.relative_to(root).as_posix()))
    return sorted(changes, key=lambda c: c[1])


def step_record(args, root: Path, since: dt.datetime, git: bool, ignore: set, cleaned: int = 0):
    say("[2/5 기록] 변경된 파일을 기록합니다.")
    changes = collect_changes(root, since, git, ignore)
    log = root / LOG_NAME
    lines = [f"\n## {now():%Y-%m-%d %H:%M} 작업 마무리\n"]
    if args.message:
        lines.append(f"- 메모: {args.message}\n")
    lines.append(f"- 폴더: `{root.name}`\n")
    lines.append(f"- 기준: {'git 변경사항' if git else f'{since:%Y-%m-%d %H:%M} 이후 수정된 파일'}\n")
    if changes:
        lines.append(f"- 변경 파일 {len(changes)}개:\n")
        lines += [f"  - [{k}] `{p}`\n" for k, p in changes]
    else:
        lines.append("- 변경 파일 없음\n")
    if cleaned:
        lines.append(f"- 정리한 임시 파일/폴더: {cleaned}개\n")
    if git:
        stat = run_git(root, "diff", "--stat", "HEAD", "--", ".", check=False).strip()
        if stat:
            lines.append("\n```\n" + stat + "\n```\n")
    if args.dry_run:
        say("  (dry-run) 기록할 내용:")
        say("".join(lines).rstrip())
        return changes
    new = not log.exists()
    with open(log, "a", encoding="utf-8") as fh:
        if new:
            fh.write("# 작업 기록\n")
        fh.writelines(lines)
    say(f"  {len(changes)}개 파일을 {log} 에 기록했습니다.")
    return changes


# ----------------------------------------------------------------- 2. 정리
def step_clean(args, root: Path):
    say("[1/5 정리] 임시 파일과 빈 폴더를 정리합니다.")
    file_pats = JUNK_FILES + (args.clean or [])
    removed = 0
    for cur, dirs, files in walk(root):
        for d in list(dirs):
            if any(fnmatch.fnmatch(d, pat) for pat in JUNK_DIRS):
                target = cur / d
                say(f"  삭제(폴더): {target.relative_to(root)}")
                if not args.dry_run:
                    shutil.rmtree(target, ignore_errors=True)
                dirs.remove(d)
                removed += 1
        for f in files:
            if any(fnmatch.fnmatch(f, pat) for pat in file_pats):
                target = cur / f
                say(f"  삭제: {target.relative_to(root)}")
                if not args.dry_run:
                    try:
                        target.unlink()
                    except OSError as e:
                        say(f"    ! 삭제 실패: {e}")
                        continue
                removed += 1
    # 빈 폴더 정리 (안쪽부터)
    if not args.keep_empty:
        for cur, dirs, files in sorted(walk(root), key=lambda t: len(t[0].parts), reverse=True):
            if cur == root:
                continue
            try:
                if not any(cur.iterdir()):
                    say(f"  삭제(빈 폴더): {cur.relative_to(root)}")
                    if not args.dry_run:
                        cur.rmdir()
                    removed += 1
            except OSError:
                pass
    say(f"  정리 항목 {removed}개.")
    return removed


# ----------------------------------------------------------------- 3. 저장
def step_save(args, root: Path, git: bool):
    say("[3/5 저장] 변경사항을 저장합니다.")
    if not git:
        say("  git 저장소가 아니라서 커밋은 건너뜁니다. (--backup 으로 zip 백업을 권장)")
        return
    msg = f"작업 마무리 자동 저장 ({now():%Y-%m-%d %H:%M})"
    if args.message:
        msg += f"\n\n{args.message}"
    if args.dry_run:
        say(f"  (dry-run) git add -A . && git commit -m \"{msg.splitlines()[0]}\"" + (" && git push" if args.push else ""))
        return
    run_git(root, "add", "-A", "--", ".")
    if not run_git(root, "diff", "--cached", "--name-only").strip():
        say("  커밋할 변경사항이 없습니다.")
    else:
        run_git(root, "commit", "-m", msg)
        say("  커밋 완료: " + run_git(root, "log", "-1", "--format=%h %s").strip())
    if args.push:
        branch = run_git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        say(f"  push 중... ({branch})")
        last = ""
        for i in range(4):
            r = subprocess.run(["git", "-C", str(root), "push", "-u", "origin", branch],
                               capture_output=True, text=True, errors="replace")
            if r.returncode == 0:
                say("  push 완료.")
                break
            last = r.stderr.strip()
            say(f"    push 실패, {2 ** (i + 1)}초 후 재시도...")
            time.sleep(2 ** (i + 1))
        else:
            raise StepError(f"git push 실패:\n{last}")


# ----------------------------------------------------------------- 4. 백업
def step_backup(args, root: Path):
    if not args.backup:
        say("[4/5 백업] 건너뜀 (--backup 을 주면 zip 백업)")
        return
    dest_dir = Path(args.backup).expanduser().resolve()
    zip_path = dest_dir / f"{root.name}_{now():%Y%m%d_%H%M%S}.zip"
    say(f"[4/5 백업] {zip_path} 로 압축합니다.")
    if args.dry_run:
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for cur, _dirs, files in walk(root):
            for f in files:
                p = cur / f
                if p.resolve() == zip_path:
                    continue
                zf.write(p, Path(root.name) / p.relative_to(root))
                count += 1
    say(f"  {count}개 파일 압축 완료 ({zip_path.stat().st_size / 1024:.1f} KB).")


# ----------------------------------------------------------------- 5. 종료
def shutdown_command():
    system = platform.system()
    if system == "Windows":
        return ["shutdown", "/s", "/t", "0"]
    if system == "Darwin":
        return ["osascript", "-e", 'tell application "System Events" to shut down']
    if shutil.which("systemctl"):
        return ["systemctl", "poweroff"]
    return ["shutdown", "-h", "now"]


def step_shutdown(args):
    cmd = shutdown_command()
    if args.no_shutdown:
        say("[5/5 종료] --no-shutdown: 컴퓨터는 끄지 않습니다.")
        return
    if args.dry_run:
        say(f"[5/5 종료] (dry-run) {args.delay}초 후 실행할 명령: {' '.join(cmd)}")
        return
    if args.scheduled:
        # 훅에서 실행될 때: 이 프로그램이 끝난 뒤에도 OS 가 알아서 끄도록 예약만 걸고 바로 끝낸다
        if platform.system() == "Windows":
            sched = ["shutdown", "/s", "/t", str(args.delay), "/c",
                     f"Claude Code 작업 완료 - {args.delay}초 후 종료합니다. 취소: disarm_shutdown.bat 또는 shutdown /a"]
            r = subprocess.run(sched, capture_output=True, text=True, errors="replace")
            if r.returncode != 0:
                raise StepError(f"종료 예약 실패: {' '.join(sched)}\n{r.stdout}{r.stderr}")
        else:
            subprocess.Popen(["sh", "-c", f"sleep {int(args.delay)}; " + " ".join(f"'{c}'" for c in cmd)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        say(f"[5/5 종료] {args.delay}초 후 컴퓨터 종료를 예약했습니다.")
        return
    say(f"[5/5 종료] {args.delay}초 후 컴퓨터를 종료합니다. 취소하려면 Ctrl+C 를 누르세요.")
    try:
        for left in range(args.delay, 0, -1):
            print(f"\r  종료까지 {left:3d}초 ", end="", flush=True)
            time.sleep(1)
        print()
    except KeyboardInterrupt:
        say("\n  종료를 취소했습니다. (기록·저장은 이미 끝났습니다)")
        return
    say("  컴퓨터를 종료합니다. 수고하셨습니다!")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise StepError(f"종료 명령 실패 (관리자 권한이 필요할 수 있습니다): {' '.join(cmd)}")


# ----------------------------------------------------------------- main
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="코딩이 끝나면 기록 → 정리 → 저장 → 백업 → 컴퓨터 종료",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="예시:\n"
               "  python finish_and_shutdown.py D:\\work\\myproj --dry-run\n"
               "  python finish_and_shutdown.py D:\\work\\myproj --idle 10 --backup D:\\backup\n"
               "  python finish_and_shutdown.py . --wait-process Code.exe --push -m \"로그인 기능 완료\"\n")
    p.add_argument("folder", nargs="?", default=None, help="작업 폴더 (기본: 현재 폴더 / 훅에서는 Claude Code 작업 폴더)")
    p.add_argument("-m", "--message", help="기록/커밋에 남길 메모")
    g = p.add_argument_group("대기 (둘 다 없으면 바로 실행)")
    g.add_argument("--idle", type=float, metavar="분", help="폴더에 이 시간(분) 동안 변경이 없으면 완료로 판단")
    g.add_argument("--wait-process", metavar="이름", help="이 프로그램이 종료되면 완료로 판단 (예: Code.exe, acad.exe)")
    g.add_argument("--poll", type=int, default=30, metavar="초", help="확인 간격 (기본 30초)")
    g = p.add_argument_group("기록/정리/저장")
    g.add_argument("--since", metavar="YYYY-MM-DD[ HH:MM]",
                   help="git 이 아닐 때 이 시각 이후 바뀐 파일을 기록 (기본: 오늘 0시)")
    g.add_argument("--clean", action="append", metavar="패턴", help="추가로 지울 파일 패턴 (여러 번 가능, 예: *.bak)")
    g.add_argument("--keep-empty", action="store_true", help="빈 폴더를 지우지 않음")
    g.add_argument("--no-clean", action="store_true", help="정리 단계 건너뜀")
    g.add_argument("--push", action="store_true", help="커밋 후 git push 까지")
    g.add_argument("--backup", metavar="폴더", help="이 폴더에 zip 백업 생성")
    g = p.add_argument_group("종료")
    g.add_argument("--delay", type=int, default=60, metavar="초", help="종료 전 카운트다운 (기본 60초)")
    g.add_argument("--no-shutdown", action="store_true", help="모든 작업 후 컴퓨터는 끄지 않음")
    g.add_argument("--force", action="store_true", help="중간 단계가 실패해도 컴퓨터 종료")
    g.add_argument("--dry-run", action="store_true", help="실제로 바꾸지 않고 무엇을 할지만 보여줌")
    g = p.add_argument_group("Claude Code 연동 (작업이 끝나면 자동 실행)")
    g.add_argument("--install-hook", action="store_true", help="Claude Code 설정에 Stop 훅 등록 (처음 한 번)")
    g.add_argument("--uninstall-hook", action="store_true", help="등록한 Stop 훅 제거")
    g.add_argument("--arm", action="store_true", help="종료 예약: Claude 가 다음에 작업을 끝내면 실행 (함께 준 옵션 사용)")
    g.add_argument("--disarm", action="store_true", help="종료 예약 취소")
    g.add_argument("--status", action="store_true", help="훅 등록/예약 상태 보기")
    g.add_argument("--hook", action="store_true", help=argparse.SUPPRESS)   # Claude Code 가 호출
    g.add_argument("--hold", action="store_true", help=argparse.SUPPRESS)   # 끝난 뒤 창 유지
    g.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)  # OS 예약 종료 사용
    return p.parse_args(argv)


# ----------------------------------------------------------------- Claude Code 연동
def settings_path() -> Path:
    return CLAUDE_DIR / "settings.json"


def load_settings():
    sp = settings_path()
    if not sp.exists():
        return {}
    try:
        return json.loads(sp.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as e:
        raise StepError(f"{sp} 이 올바른 JSON 이 아닙니다: {e}")


def save_settings(data):
    sp = settings_path()
    sp.parent.mkdir(parents=True, exist_ok=True)
    if sp.exists():
        shutil.copy2(sp, sp.with_name(f"settings.json.bak_{now():%Y%m%d_%H%M%S}"))
    sp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def hook_entries(data):
    return data.setdefault("hooks", {}).setdefault("Stop", [])


def has_our_hook(group):
    return any(HOOK_MARK in h.get("command", "") for h in group.get("hooks", []))


def install_hook():
    data = load_settings()
    stop = hook_entries(data)
    stop[:] = [g for g in stop if not has_our_hook(g)]
    cmd = f'"{sys.executable}" "{Path(__file__).resolve()}" --hook'
    stop.append({"hooks": [{"type": "command", "command": cmd, "timeout": 600}]})
    save_settings(data)
    say(f"Stop 훅을 등록했습니다: {settings_path()}")
    say(f"  명령: {cmd}")
    say("  ※ 이미 실행 중인 Claude Code 에는 바로 적용되지 않을 수 있습니다.")
    say("    Claude Code 에서 /hooks 를 한 번 열어 확인하거나, Claude Code 를 다시 시작하세요.")
    say("  ※ 훅만 등록하면 아무 일도 일어나지 않습니다. 끄고 싶은 날 --arm 으로 예약하세요.")


def uninstall_hook():
    data = load_settings()
    stop = hook_entries(data)
    before = len(stop)
    stop[:] = [g for g in stop if not has_our_hook(g)]
    if not stop:
        data["hooks"].pop("Stop")
        if not data["hooks"]:
            data.pop("hooks")
    save_settings(data)
    say(f"Stop 훅 {before - len(stop)}개를 제거했습니다.")


def strip_args(argv, folder):
    out, removed = [], False
    for a in argv:
        if a == "--arm":
            continue
        if folder is not None and not removed and a == folder:
            removed = True
            continue
        out.append(a)
    return out


def arm(args, argv):
    folder = str(Path(args.folder).expanduser().resolve()) if args.folder else None
    if folder and not Path(folder).is_dir():
        raise StepError(f"폴더가 없습니다: {folder}")
    info = {"folder": folder, "argv": strip_args(argv, args.folder), "armed_at": f"{now():%Y-%m-%d %H:%M}"}
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    ARM_FILE.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    hooked = any(has_our_hook(g) for g in load_settings().get("hooks", {}).get("Stop", []))
    say("종료 예약 완료: Claude Code 가 다음에 작업을 끝내면 마무리 후 컴퓨터를 끕니다.")
    say(f"  폴더: {folder or '(Claude Code 작업 폴더)'}")
    say(f"  옵션: {' '.join(info['argv']) or '(기본)'}")
    say("  취소: --disarm")
    if not hooked:
        say("  ! 아직 Stop 훅이 등록되지 않았습니다. 먼저 --install-hook 을 실행하세요.")


def disarm():
    if platform.system() == "Windows":        # 이미 걸린 Windows 종료 예약도 취소
        r = subprocess.run(["shutdown", "/a"], capture_output=True)
        if r.returncode == 0:
            say("예약되어 있던 Windows 종료를 취소했습니다.")
    if ARM_FILE.exists():
        ARM_FILE.unlink()
        say("종료 예약을 취소했습니다.")
    else:
        say("예약된 종료가 없습니다.")


def status():
    hooked = any(has_our_hook(g) for g in load_settings().get("hooks", {}).get("Stop", []))
    say(f"Stop 훅 등록: {'예' if hooked else '아니오'} ({settings_path()})")
    if ARM_FILE.exists():
        info = json.loads(ARM_FILE.read_text(encoding="utf-8"))
        say(f"종료 예약: 켜짐 ({info.get('armed_at')}) 폴더={info.get('folder') or '(Claude Code 작업 폴더)'} "
            f"옵션={' '.join(info.get('argv', [])) or '(기본)'}")
    else:
        say("종료 예약: 꺼짐")
    if HOOK_LOG.exists():
        lines = HOOK_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        say(f"\n최근 로그 ({HOOK_LOG}):")
        for line in lines[-15:]:
            say("  " + line)
    else:
        say("\n로그 없음: 훅이 한 번도 호출되지 않았습니다 (Claude Code 가 훅을 불러오지 않음).")


def hook_log(msg):
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    with open(HOOK_LOG, "a", encoding="utf-8") as fh:
        fh.write(f"{now():%Y-%m-%d %H:%M:%S} {msg}\n")


def run_hook():
    """Claude Code 의 Stop 훅에서 호출. 예약이 있을 때만 이 자리에서 마무리하고 OS 종료를 예약한다."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    if payload.get("stop_hook_active"):
        return 0
    if not ARM_FILE.exists():
        hook_log(f"훅 호출됨 - 예약 없음 (폴더: {payload.get('cwd')})")
        return 0
    try:
        info = json.loads(ARM_FILE.read_text(encoding="utf-8"))
    except Exception:
        info = {}
    ARM_FILE.unlink(missing_ok=True)          # 한 번만 실행 (연달아 꺼지는 것 방지)
    folder = info.get("folder") or payload.get("cwd") or os.getcwd()
    argv = [folder, *info.get("argv", []), "--scheduled"]
    hook_log(f"훅 호출됨 - 예약 실행: {argv}")
    old = sys.stdout, sys.stderr
    try:
        with open(HOOK_LOG, "a", encoding="utf-8") as fh:
            sys.stdout = sys.stderr = fh
            rc = finish(parse_args(argv))
    except BaseException as e:               # 어떤 오류든 로그에 남긴다
        import traceback
        hook_log("오류: " + traceback.format_exc())
        rc = 1
    finally:
        sys.stdout, sys.stderr = old
    hook_log(f"마무리 끝 (결과 코드 {rc}{'' if rc == 0 else ', 실패하여 종료하지 않음'})")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(argv)
    try:
        if args.hook:
            return run_hook()
        if args.install_hook:
            return install_hook() or 0
        if args.uninstall_hook:
            return uninstall_hook() or 0
        if args.arm:
            return arm(args, argv) or 0
        if args.disarm:
            return disarm() or 0
        if args.status:
            return status() or 0
    except StepError as e:
        say(f"! {e}")
        return 1
    rc = finish(args)
    if args.hold and rc != 0 and sys.stdin and sys.stdin.isatty():
        input("\nEnter 를 누르면 창을 닫습니다...")
    return rc


def finish(args):
    root = Path(args.folder or ".").expanduser().resolve()
    if not root.is_dir():
        say(f"폴더가 없습니다: {root}")
        return 2
    since = (dt.datetime.fromisoformat(args.since) if args.since
             else now().replace(hour=0, minute=0, second=0, microsecond=0))
    ignore = {(root / LOG_NAME).resolve()}

    say(f"=== 작업 마무리: {root} ===" + ("  [dry-run]" if args.dry_run else ""))
    try:
        step_wait(args, root, ignore)
    except KeyboardInterrupt:
        say("\n대기를 중단했습니다. 아무것도 하지 않고 끝냅니다.")
        return 1

    git = is_git_repo(root)
    failed = []
    cleaned = [0]

    def clean():
        if args.no_clean:
            say("[1/5 정리] 건너뜀")
        else:
            cleaned[0] = step_clean(args, root)

    steps = [
        ("정리", clean),
        ("기록", lambda: step_record(args, root, since, git, ignore, cleaned[0])),
        ("저장", lambda: step_save(args, root, git)),
        ("백업", lambda: step_backup(args, root)),
    ]
    for name, fn in steps:
        try:
            fn()
        except (StepError, OSError, subprocess.SubprocessError) as e:
            say(f"  ! {name} 단계 실패: {e}")
            failed.append(name)

    if failed and not args.force:
        say(f"\n실패한 단계가 있어 컴퓨터를 끄지 않습니다: {', '.join(failed)}")
        say("(확인 후 다시 실행하거나, 무시하려면 --force)")
        return 1
    try:
        step_shutdown(args)
    except StepError as e:
        say(f"  ! {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
