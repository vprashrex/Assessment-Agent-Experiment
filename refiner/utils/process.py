"""Background run processes."""

from __future__ import annotations

import os
import subprocess


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a finished child that was never reaped still answers kill(0); check it is not a zombie
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        return bool(out) and not out.startswith("Z")
    except Exception:
        return True


def reap(pid: int) -> None:
    """Collect a finished child of this process so it does not linger as a zombie."""
    try:
        os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass
