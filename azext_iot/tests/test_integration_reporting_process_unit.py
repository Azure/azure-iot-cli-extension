# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
import textwrap
from threading import Thread
from time import monotonic


def test_xdist_reports_failed_call_while_teardown_is_still_running(tmp_path):
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    test_file = tmp_path / "test_progress_int.py"
    test_file.write_text(textwrap.dedent("""
        from pathlib import Path
        import time
        import pytest

        @pytest.fixture
        def resource():
            yield
            deadline = time.monotonic() + 10
            while not Path("release-teardown").exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Parent did not receive the live phase report")
                time.sleep(0.05)

        def test_example(resource):
            raise RuntimeError("Deliberate call failure")
    """), encoding="utf-8")
    root = str(Path(__file__).resolve().parents[2])
    environment = dict(
        os.environ,
        AZURE_TEST_RUN_LIVE="False",
        azext_iot_testrg="unit-test-rg",
        PYTHONPATH=os.pathsep.join(filter(None, (root, os.environ.get("PYTHONPATH")))),
    )
    command = [
        sys.executable, "-m", "pytest", "-c", str(config), "--rootdir", str(tmp_path),
        "-p", "azext_iot.tests.conftest", "-p", "no:rerunfailures",
        "-n", "2", "--dist=loadfile", "--integration-progress-interval=1", str(test_file),
    ]
    output = bytearray()
    received_live_report = False
    with subprocess.Popen(
        command, cwd=tmp_path, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    ) as process:
        lines = Queue()

        def read_output():
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        reader = Thread(target=read_output, daemon=True)
        reader.start()
        try:
            deadline = monotonic() + 25
            while monotonic() < deadline:
                try:
                    data = lines.get(timeout=1)
                except Empty:
                    continue
                if data is None:
                    break
                output.extend(data)
                if b"[integration progress] WAIT teardown:" in output:
                    assert b"[integration progress] END call failed:" in output
                    assert process.poll() is None
                    received_live_report = True
                    break
        finally:
            (tmp_path / "release-teardown").write_text("", encoding="utf-8")
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise
            reader.join(timeout=1)
    assert received_live_report, output.decode(errors="replace")
    assert process.returncode == 1, output.decode(errors="replace")
