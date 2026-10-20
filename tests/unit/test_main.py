import subprocess
import sys

import pytest

from main import Service, check_children, stop_services


def test_failed_child_is_detected_and_siblings_are_stopped(tmp_path):
    failed_service = Service("failing test child", (sys.executable,), tmp_path, 8101)
    sibling_service = Service("long-running test child", (sys.executable,), tmp_path, 8102)
    failed = subprocess.Popen([sys.executable, "-c", "raise SystemExit(7)"])
    sibling = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    processes = [(failed_service, failed), (sibling_service, sibling)]
    try:
        assert failed.wait(timeout=5) == 7
        with pytest.raises(ChildProcessError, match="failing test child exited unexpectedly with status 7"):
            check_children(processes)
        stop_services(processes)
        assert sibling.poll() is not None
    finally:
        for process in (failed, sibling):
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
