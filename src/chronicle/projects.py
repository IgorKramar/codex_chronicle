import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .config import save
from .privacy import redact, safe_path


def git(cwd, *args):
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            timeout=2,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def canonical_remote(remote):
    if not remote:
        return ""
    if "://" in remote:
        p = urlsplit(remote)
        if p.scheme not in {"http", "https", "ssh", "git"} or not p.hostname:
            return ""  # local paths are not a cross-machine project identity
        host, path = p.hostname.lower(), p.path
    elif ":" in remote and "@" in remote.split(":", 1)[0]:
        host, path = remote.split(":", 1)
        host = host.rsplit("@", 1)[-1].lower()
    else:
        return ""
    path = path.strip("/").removesuffix(".git")
    return f"{host}/{path}" if path else ""


def discover(cwd, cfg):
    root = Path(git(cwd, "rev-parse", "--show-toplevel") or cwd).resolve()
    remote = canonical_remote(git(root, "remote", "get-url", "origin"))
    pid = cfg["bindings"].get(str(root))
    if not pid:
        pid = (
            str(uuid.uuid5(uuid.NAMESPACE_URL, "chronicle:" + remote))
            if remote
            else str(uuid.uuid4())
        )
        cfg["bindings"][str(root)] = pid
    cfg["projects"].setdefault(pid, {"name": root.name, "remote": remote, "policy": "local"})
    save(cfg)
    worktree = str(uuid.uuid5(uuid.NAMESPACE_URL, cfg["computer_id"] + ":" + str(root)))
    return pid, root, worktree


def snapshot(root):
    # Names only, never git diff or environment/config contents.
    files = git(root, "diff", "--name-only", "HEAD").splitlines()
    files += git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return redact(
        {
            "branch": git(root, "branch", "--show-current"),
            "commit": git(root, "rev-parse", "HEAD"),
            "files": sorted({p for p in files if safe_path(p)})[:500],
        }
    )
