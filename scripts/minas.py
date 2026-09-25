#!/usr/bin/env python3
"""MINAS Samba toolkit — agent file ops on Xiaomi Smart Storage over SMB/CIFS.

Primary transport is Samba (port 445). Works with UNC paths on Windows.
No secrets in source: configure via environment variables.

Environment:
  MINAS_HOST     NAS hostname or IP (e.g. 192.168.1.50 or minas.local)
  MINAS_SHARE    Share name to use as default root (optional)
  MINAS_USER     SMB username (optional if Windows already has a session)
  MINAS_PASSWORD_FILE  File holding the SMB password (preferred non-interactive way)
  MINAS_PASS     SMB password env fallback (last resort; a security warning is printed;
                 prefer MINAS_PASSWORD_FILE or the interactive prompt)
  MINAS_ROOT     Restrict every remote file op to this UNC prefix. Unset = any UNC path.
                 Remote paths must ALWAYS be UNC (\\\\host\\share\\...); local paths
                 (C:\\...) and "../" escapes outside MINAS_ROOT are rejected.

Examples:
  python minas.py shares
  python minas.py ls //NAS/share
  python minas.py ls //NAS/share --json
  python minas.py du //NAS/share/folder --max-depth 2
  python minas.py get //NAS/share/a.txt ./a.txt
  python minas.py put ./a.txt //NAS/share/a.txt
  python minas.py mkdir //NAS/share/work
  python minas.py mv //NAS/share/a.txt //NAS/share/work/a.txt
  python minas.py rm //NAS/share/work --recursive
  python minas.py find //NAS/share --name "*.mp4" --max-depth 3

Exit codes: 0 ok, 1 usage/error, 2 not found, 3 auth/network.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

IS_WINDOWS = os.name == "nt"


# --------------- path helpers ---------------

def norm_unc(path: str) -> str:
    """Normalize a UNC or local path to backslash form on Windows."""
    p = path.strip().replace("/", "\\")
    if p.startswith("\\\\"):
        return "\\\\" + p[2:].lstrip("\\")
    return p


def parse_unc(path: str) -> tuple[str, str, str]:
    """Return (host, share, inner). Accepts //host/share/inner or \\\\host\\share\\inner."""
    p = path.replace("/", "\\")
    if not p.startswith("\\\\"):
        raise ValueError(f"not a UNC path: {path}")
    parts = p[2:].split("\\")
    if len(parts) < 2:
        raise ValueError(f"UNC needs host and share: {path}")
    host, share = parts[0], parts[1]
    inner = "\\".join(parts[2:])
    return host, share, inner


def collapse_unc(path: str) -> str:
    """Lexically drop '.'/'..' segments in a normalized UNC path.

    '..' may not climb above \\host\\share (raises ValueError instead).
    """
    p = norm_unc(path)
    if not p.startswith("\\\\"):
        return p
    parts = p[2:].split("\\")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(f"UNC needs host and share: {path}")
    keep = parts[:2]
    for seg in parts[2:]:
        if seg in ("", "."):
            continue
        if seg == "..":
            if len(keep) <= 2:
                raise ValueError(f"path escapes share root: {path}")
            keep.pop()
            continue
        keep.append(seg)
    return "\\\\" + "\\".join(keep)


def safe_remote(path: str) -> str:
    """校验并规范化远端路径：必须是 UNC，且（若设置 MINAS_ROOT）落在其前缀之下。

    先做词法折叠去掉 ../，再比对前缀，防止用 .. 绕过 MINAS_ROOT。
    非 UNC 路径（如 C:\\...）一律拒绝。MINAS_ROOT 未设置时允许任意 UNC。
    """
    p = collapse_unc(path)
    if not p.startswith("\\\\"):
        raise ValueError(f"remote path must be UNC (\\\\host\\share\\...), got: {path}")
    root = os.environ.get("MINAS_ROOT", "").strip()
    if root:
        r = collapse_unc(root)
        if p.lower() != r.lower() and not p.lower().startswith(r.lower().rstrip("\\") + "\\"):
            raise ValueError(f"path outside MINAS_ROOT ({root}): {path}")
    return p


def to_local(path: str) -> Path:
    return Path(norm_unc(path))


# --------------- SMB session helpers ---------------

def smb_env() -> dict[str, str]:
    return {
        "host": os.environ.get("MINAS_HOST", ""),
        "share": os.environ.get("MINAS_SHARE", ""),
        "user": os.environ.get("MINAS_USER", ""),
        "password": os.environ.get("MINAS_PASS", ""),
    }


def run_net(args: list[str], timeout: int = 30, capture: bool = True) -> tuple[int, str, str]:
    exe = shutil.which("net") or shutil.which("net.exe") or "net"
    try:
        if not capture:
            # 交互模式：不接管 stdio，让 net use 的 "*" 密码提示直接显示给用户
            p = subprocess.run([exe, *args], timeout=None)
            return p.returncode, "", ""
        p = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", "net command not found (use Windows or install Samba client)"
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"


def resolve_password() -> str | None:
    """按优先级解析 SMB 密码，避免明文进入命令行。

    1. 可交互控制台 → 返回 "*"，交给 net use 的交互式密码提示（密码不进命令行）；
    2. MINAS_PASSWORD_FILE → 从文件读取，读取后提示收紧文件权限；
    3. MINAS_PASSWORD / MINAS_PASS → 最后兼容，打印安全警告。
    """
    # 1) 可交互控制台：优先交互提示
    if IS_WINDOWS and sys.stdin.isatty() and sys.stdout.isatty():
        return "*"
    # 2) 密码文件（非交互场景，如 agent/计划任务）
    pw_file = os.environ.get("MINAS_PASSWORD_FILE", "").strip()
    if pw_file:
        try:
            pw = Path(pw_file).read_text(encoding="utf-8").strip("\r\n")
        except OSError as e:
            print(f"cannot read MINAS_PASSWORD_FILE ({pw_file}): {e}", file=sys.stderr)
            return None
        print(
            f"password loaded from {pw_file}; restrict it to your own user only "
            f'(e.g. icacls "{pw_file}" /inheritance:r /grant:r %USERNAME%:F)',
            file=sys.stderr,
        )
        return pw
    # 3) 环境变量（最后兼容，有泄露风险）
    pw = os.environ.get("MINAS_PASSWORD") or os.environ.get("MINAS_PASS") or ""
    if pw:
        print(
            "security warning: SMB password taken from environment "
            "(MINAS_PASSWORD/MINAS_PASS); prefer MINAS_PASSWORD_FILE or the "
            "interactive prompt",
            file=sys.stderr,
        )
        return pw
    return None


def ensure_session(host: str, share: str | None = None) -> None:
    """Best-effort: connect IPC$/share with env credentials if provided."""
    env = smb_env()
    user = env["user"]
    if not user:
        return  # rely on existing Windows session
    password = resolve_password()
    interactive = password == "*"
    target = f"\\\\{host}\\{share}" if share else f"\\\\{host}\\IPC$"
    # disconnect first to avoid 1219 (multiple credentials)
    run_net(["use", target, "/delete", "/y"])
    args = ["use", target, f"/user:{user}"]
    if password:
        # "*" 时 net 交互式提示，密码不进命令行
        args.append(password)
    code, out, err = run_net(args, capture=not interactive)
    if code != 0 and share:
        # try IPC$ only
        run_net(["use", f"\\\\{host}\\IPC$", "/delete", "/y"])
        args = ["use", f"\\\\{host}\\IPC$", f"/user:{user}"]
        if password:
            args.append(password)
        run_net(args, capture=not interactive)


def list_shares(host: str) -> list[str]:
    """List share names on host via net view (Windows)."""
    ensure_session(host, None)
    code, out, err = run_net(["view", f"\\\\{host}"])
    text = out + "\n" + err
    names: list[str] = []
    # net view output is locale-dependent; grab tokens that look like share rows.
    # Prefer lines after the dashed separator.
    lines = text.splitlines()
    seen_sep = False
    for line in lines:
        if re.match(r"^-{3,}", line.strip()):
            seen_sep = True
            continue
        if not seen_sep:
            continue
        if not line.strip():
            continue
        # columns: Share name  Type  Used as  Comment
        m = re.match(r"^(\S+(?:\s\S+)*?)\s{2,}(\S+)\s{2,}(.*?)$", line)
        if m:
            names.append(m.group(1).strip())
            continue
        # fallback: first token
        toks = line.split()
        if toks:
            names.append(toks[0])
    # unique preserve order
    out_names = []
    for n in names:
        if n and n not in out_names and n.lower() not in {"the", "command", "completed", "successfully", "there"}:
            out_names.append(n)
    return out_names


# --------------- file ops ---------------

def cmd_shares(_client: Any, args: argparse.Namespace) -> int:
    host = args.host or smb_env()["host"]
    if not host:
        print("set MINAS_HOST or pass --host", file=sys.stderr)
        return 1
    names = list_shares(host)
    if args.json:
        print(json.dumps({"host": host, "shares": names}, ensure_ascii=False, indent=2))
    else:
        print(f"host: {host}")
        for n in names:
            print(f"  {n}")
    return 0


def cmd_ls(_client: Any, args: argparse.Namespace) -> int:
    path = safe_remote(args.path)
    p = to_local(path)
    if not p.exists():
        print(f"not found: {path}", file=sys.stderr)
        return 2
    ensure_session(*parse_unc(path)[:2])
    if p.is_file():
        items = [{"name": p.name, "path": str(p), "size": p.stat().st_size, "is_dir": False}]
    else:
        items = []
        for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            try:
                st = child.stat()
                size = st.st_size if child.is_file() else 0
            except OSError:
                size = 0
            items.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "size": size,
                    "is_dir": child.is_dir(),
                    "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)) if size or child.is_file() else "",
                }
            )
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    for it in items:
        kind = "d" if it["is_dir"] else "-"
        size = fmt_size(it["size"]) if not it["is_dir"] else ""
        print(f"{kind} {size:>10}  {it['name']}")
    return 0


def fmt_size(n: float) -> str:
    n = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def dir_size(path: Path, max_depth: int, depth: int = 0) -> tuple[int, int]:
    total = 0
    count = 0
    try:
        for child in path.iterdir():
            if child.is_dir():
                if depth < max_depth:
                    t, c = dir_size(child, max_depth, depth + 1)
                    total += t
                    count += c
            else:
                try:
                    total += child.stat().st_size
                    count += 1
                except OSError:
                    pass
    except OSError:
        pass
    return total, count


def cmd_du(_client: Any, args: argparse.Namespace) -> int:
    path = safe_remote(args.path)
    p = to_local(path)
    if not p.exists():
        print(f"not found: {path}", file=sys.stderr)
        return 2
    ensure_session(*parse_unc(path)[:2])
    rows = []
    if p.is_file():
        rows.append((p.name, p.stat().st_size, 1, False))
    else:
        for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if child.is_dir():
                t, c = dir_size(child, args.max_depth)
                rows.append((child.name, t, c, True))
            else:
                try:
                    rows.append((child.name, child.stat().st_size, 1, False))
                except OSError:
                    rows.append((child.name, 0, 0, False))
        rows.sort(key=lambda r: -r[1])
    if args.json:
        print(
            json.dumps(
                [{"name": n, "bytes": b, "files": c, "is_dir": d} for n, b, c, d in rows],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    grand = 0
    for name, total, count, is_dir in rows:
        grand += total
        mark = "/" if is_dir else ""
        print(f"{fmt_size(total):>10}  {count:>6}  {name}{mark}")
    print("-" * 40)
    print(f"{fmt_size(grand):>10}  TOTAL")
    return 0


def cmd_df(_client: Any, args: argparse.Namespace) -> int:
    path = args.path
    if not path:
        env = smb_env()
        if env["host"] and env["share"]:
            path = f"//{env['host']}/{env['share']}"
        else:
            print("pass a UNC path or set MINAS_HOST and MINAS_SHARE", file=sys.stderr)
            return 1
    path = safe_remote(path)
    p = to_local(path)
    ensure_session(*parse_unc(path)[:2])
    try:
        usage = shutil.disk_usage(str(p if p.is_dir() else p.parent))
        info = {
            "path": str(p),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "total_human": fmt_size(usage.total),
            "used_human": fmt_size(usage.used),
            "free_human": fmt_size(usage.free),
        }
    except OSError as e:
        print(f"disk_usage failed: {e}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(f"path:  {info['path']}")
        print(f"total: {info['total_human']}  used: {info['used_human']}  free: {info['free_human']}")
    return 0


def cmd_get(_client: Any, args: argparse.Namespace) -> int:
    remote = to_local(safe_remote(args.remote))
    local = Path(args.local)
    if not remote.exists():
        print(f"not found: {args.remote}", file=sys.stderr)
        return 2
    if local.is_dir():
        local = local / remote.name
    local.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(remote), str(local))
    print(f"saved {local} ({fmt_size(local.stat().st_size)})")
    return 0


def cmd_put(_client: Any, args: argparse.Namespace) -> int:
    local = Path(args.local)
    if not local.exists():
        print(f"local not found: {local}", file=sys.stderr)
        return 2
    if local.is_dir():
        print("local is a directory; copy files one by one or use robocopy", file=sys.stderr)
        return 1
    remote = to_local(safe_remote(args.remote))
    remote.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(local), str(remote))
    print(f"uploaded {local} -> {remote} ({fmt_size(local.stat().st_size)})")
    return 0


def cmd_cat(_client: Any, args: argparse.Namespace) -> int:
    remote = to_local(safe_remote(args.path))
    if not remote.exists():
        print(f"not found: {args.path}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(remote.read_bytes())
    return 0


def cmd_mkdir(_client: Any, args: argparse.Namespace) -> int:
    remote = to_local(safe_remote(args.path))
    remote.mkdir(parents=True, exist_ok=True)
    print(f"mkdir ok: {remote}")
    return 0


def cmd_rm(_client: Any, args: argparse.Namespace) -> int:
    # 递归删除严格走 safe_remote：非 UNC 或越过 MINAS_ROOT 一律拒绝
    remote = to_local(safe_remote(args.path))
    if not remote.exists():
        print(f"not found: {args.path}", file=sys.stderr)
        return 2
    if remote.is_dir():
        if not args.recursive:
            print("refusing to delete directory without --recursive", file=sys.stderr)
            return 1
        shutil.rmtree(str(remote))
    else:
        remote.unlink()
    print(f"removed: {remote}")
    return 0


def cmd_mv(_client: Any, args: argparse.Namespace) -> int:
    src = to_local(safe_remote(args.src))
    dst = to_local(safe_remote(args.dst))
    if not src.exists():
        print(f"not found: {args.src}", file=sys.stderr)
        return 2
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and not args.force:
        print(f"destination exists (use --force): {dst}", file=sys.stderr)
        return 1
    shutil.move(str(src), str(dst))
    print(f"moved {src} -> {dst}")
    return 0


def cmd_cp(_client: Any, args: argparse.Namespace) -> int:
    src = to_local(safe_remote(args.src))
    dst = to_local(safe_remote(args.dst))
    if not src.exists():
        print(f"not found: {args.src}", file=sys.stderr)
        return 2
    if src.is_dir():
        if dst.exists() and not args.force:
            print(f"destination exists (use --force): {dst}", file=sys.stderr)
            return 1
        shutil.copytree(str(src), str(dst))
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and not args.force:
            print(f"destination exists (use --force): {dst}", file=sys.stderr)
            return 1
        shutil.copy2(str(src), str(dst))
    print(f"copied {src} -> {dst}")
    return 0


def cmd_find(_client: Any, args: argparse.Namespace) -> int:
    root = to_local(safe_remote(args.path))
    if not root.exists():
        print(f"not found: {args.path}", file=sys.stderr)
        return 2
    found = []

    def rec(path: Path, depth: int) -> None:
        try:
            children = list(path.iterdir())
        except OSError:
            return
        for child in children:
            is_dir = child.is_dir()
            name_ok = True
            if args.name:
                name_ok = fnmatch.fnmatch(child.name, args.name)
            type_ok = True
            if args.files and is_dir:
                type_ok = False
            if args.dirs and not is_dir:
                type_ok = False
            if name_ok and type_ok:
                size = 0
                if not is_dir:
                    try:
                        size = child.stat().st_size
                    except OSError:
                        pass
                found.append({"path": str(child), "name": child.name, "is_dir": is_dir, "size": size})
            if is_dir and depth < args.max_depth:
                rec(child, depth + 1)

    rec(root, 0)
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=2))
    else:
        for it in found:
            mark = "/" if it["is_dir"] else ""
            print(f"{fmt_size(it['size']):>10}  {it['path']}{mark}")
    return 0


def cmd_tree(_client: Any, args: argparse.Namespace) -> int:
    root = to_local(safe_remote(args.path))

    def rec(path: Path, prefix: str, depth: int) -> None:
        try:
            children = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except OSError:
            return
        for i, child in enumerate(children):
            last = i == len(children) - 1
            branch = "└── " if last else "├── "
            extra = "/" if child.is_dir() else ""
            if not child.is_dir():
                try:
                    extra = f"  ({fmt_size(child.stat().st_size)})"
                except OSError:
                    extra = ""
            print(f"{prefix}{branch}{child.name}{extra}")
            if child.is_dir() and depth < args.max_depth:
                rec(child, prefix + ("    " if last else "│   "), depth + 1)

    print(root)
    rec(root, "", 0)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="minas", description="Xiaomi Smart Storage Samba CLI for agents")
    p.add_argument("--host", default=os.environ.get("MINAS_HOST", ""), help="NAS host/IP")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("shares", help="list SMB shares")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--host", default=os.environ.get("MINAS_HOST", ""), help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_shares)

    sp = sub.add_parser("ls")
    sp.add_argument("path")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--host", default=os.environ.get("MINAS_HOST", ""), help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_ls)

    sp = sub.add_parser("du")
    sp.add_argument("path")
    sp.add_argument("--max-depth", type=int, default=2)
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--host", default=os.environ.get("MINAS_HOST", ""), help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_du)

    sp = sub.add_parser("tree")
    sp.add_argument("path")
    sp.add_argument("--max-depth", type=int, default=2)
    sp.add_argument("--host", default=os.environ.get("MINAS_HOST", ""), help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_tree)

    sp = sub.add_parser("df", help="disk usage of a UNC path")
    sp.add_argument("path", nargs="?", default="")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_df)

    sp = sub.add_parser("get", help="download file")
    sp.add_argument("remote")
    sp.add_argument("local")
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("put", help="upload file")
    sp.add_argument("local")
    sp.add_argument("remote")
    sp.set_defaults(func=cmd_put)

    sp = sub.add_parser("cat", help="print file")
    sp.add_argument("path")
    sp.set_defaults(func=cmd_cat)

    sp = sub.add_parser("mkdir", help="create directory")
    sp.add_argument("path")
    sp.set_defaults(func=cmd_mkdir)

    sp = sub.add_parser("rm", help="delete file/dir")
    sp.add_argument("path")
    sp.add_argument("-r", "--recursive", action="store_true")
    sp.set_defaults(func=cmd_rm)

    sp = sub.add_parser("mv", help="move/rename")
    sp.add_argument("src")
    sp.add_argument("dst")
    sp.add_argument("-f", "--force", action="store_true")
    sp.set_defaults(func=cmd_mv)

    sp = sub.add_parser("cp", help="copy")
    sp.add_argument("src")
    sp.add_argument("dst")
    sp.add_argument("-f", "--force", action="store_true")
    sp.set_defaults(func=cmd_cp)

    sp = sub.add_parser("find", help="find by name pattern")
    sp.add_argument("path")
    sp.add_argument("--name")
    sp.add_argument("--max-depth", type=int, default=3)
    sp.add_argument("--files", action="store_true")
    sp.add_argument("--dirs", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_find)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(None, args)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    except PermissionError as e:
        print(f"permission denied: {e}", file=sys.stderr)
        return 3
    except OSError as e:
        print(f"os error: {e}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
