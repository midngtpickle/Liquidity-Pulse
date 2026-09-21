"""
Liquidity-Pulse - Single-Writer Lock

The recorders append to gzip files. Two processes appending to one gzip file do not
produce a merged file -- they produce an unreadable one. The members interleave, and
every member after the first collision fails to decompress.

This is not hypothetical. Running `ws_feed.py --record` by hand while the scheduled
task was already recording destroyed that day's depth history: 4 gzip members, 3 of
them undecodable, 27 records recoverable out of ~20 minutes. The failure is silent at
write time and only shows up when you try to read the data back, which -- for history
whose entire purpose is to be read back months later -- is the worst possible time.

So the recorders take a lock. A second one refuses to start and says why, rather than
quietly corrupting what the first is writing.

Stale locks are handled, because the holder is a daemon that Task Scheduler restarts:
a lock naming a dead PID is taken over rather than honoured, otherwise a single crash
would stop recording until someone noticed and deleted a file.
"""

import os
import errno
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("RunLock")


class LockHeld(RuntimeError):
    """Raised when another live process already holds the lock."""


def _pid_alive(pid: int) -> bool:
    """
    Is a process with this PID running?

    On Windows, OpenProcess via ctypes is the honest check; os.kill(pid, 0) raises
    for permission reasons as well as for absence, which would make a live lock look
    stale and put us right back to two writers.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RunLock:
    """
    An advisory single-writer lock, as a context manager.

        with RunLock(workspace / "depth_history.lock", "depth recorder"):
            ...

    Advisory, not enforced by the OS: it stops the accident this project actually had
    (a scheduled daemon plus a manual run), not a determined caller.
    """

    def __init__(self, path: Path, label: str = "recorder"):
        self.path = Path(path)
        self.label = label
        self._acquired = False

    def acquire(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)

        for attempt in (1, 2):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(str(os.getpid()))
                self._acquired = True
                return self
            except OSError as err:
                if err.errno != errno.EEXIST:
                    raise
                holder = self._holder()
                if holder is not None and _pid_alive(holder):
                    raise LockHeld(
                        f"Another {self.label} is already running (PID {holder}). "
                        f"Two writers would corrupt the history file, so this one is "
                        f"stopping. Lock: {self.path}"
                    )
                # Stale: the holder died without releasing. Take it over.
                if attempt == 1:
                    logger.warning(
                        f"Removing stale {self.label} lock from PID {holder} "
                        f"(no such process)."
                    )
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass  # someone else cleaned up; retry will win or lose fairly

        raise LockHeld(f"Could not acquire {self.label} lock at {self.path}")

    def _holder(self) -> Optional[int]:
        try:
            return int(self.path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def release(self) -> None:
        if not self._acquired:
            return
        # Only remove it if it is still ours. A stale-lock takeover elsewhere could
        # otherwise have us deleting the new holder's lock on the way out.
        if self._holder() == os.getpid():
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self._acquired = False

    def __enter__(self) -> "RunLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()
