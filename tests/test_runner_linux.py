"""Exercise the actual Linux parent-death signal in CI, without any networking."""

import asyncio
import os
import signal
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "linux", reason="PR_SET_PDEATHSIG is Linux-specific")
async def test_runner_terminates_child_when_backend_parent_disappears():
    runner = Path(__file__).parents[1] / "py_modules/decky_proxy/runner.py"
    program = (
        "import os,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,sys.argv[1],str(os.getpid()),"
        "'/bin/sleep','30']); print(child.pid,flush=True); time.sleep(0.3)"
    )
    parent = await asyncio.create_subprocess_exec(
        sys.executable, "-c", program, str(runner), stdout=asyncio.subprocess.PIPE
    )
    child_pid = None
    try:
        line = await asyncio.wait_for(parent.stdout.readline(), 3)
        child_pid = int(line)
        await asyncio.wait_for(parent.wait(), 3)
        for _ in range(40):
            status = Path(f"/proc/{child_pid}/stat")
            try:
                state = await asyncio.to_thread(status.read_text)
            except FileNotFoundError:
                return
            if state.split(") ", 1)[1].startswith("Z"):
                return
            await asyncio.sleep(0.05)
        pytest.fail("Guarded child remained alive after its parent exited")
    finally:
        if parent.returncode is None:
            parent.kill()
            await parent.wait()
        if child_pid:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
