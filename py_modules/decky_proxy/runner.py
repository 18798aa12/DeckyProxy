"""Linux-only exec guard: graceful SIGTERM if the Decky backend disappears."""

import ctypes
import os
import signal
import sys


def main() -> None:
    expected_parent = int(sys.argv[1])
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "Cannot set parent-death signal")
    if os.getppid() != expected_parent:
        raise SystemExit(1)
    os.execve(sys.argv[2], sys.argv[2:], dict(os.environ))


if __name__ == "__main__":
    main()
