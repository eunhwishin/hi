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
    p.add_argument("folder", nargs="?", default=".", help="작업 폴더 (기본: 현재 폴더)")
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
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    root = Path(args.folder).expanduser().resolve()
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
