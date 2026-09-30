# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Install the checkout extension once per concurrent DPS runner, never while another phase installs.

Concurrent DPS phases share one tox environment. An unguarded `pip install -U --target` would
replace modules that sibling phases are importing and race on the checkout's build directory.
Without azext_iot_dps_install_token (standalone tox use) every invocation installs, as before.
"""

import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TOKEN_ENV = "azext_iot_dps_install_token"


def install(target, token=None, source=ROOT, run_process=subprocess.run):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    marker = target.parent / (target.name + ".install-token")
    with open(target.parent / (target.name + ".install-lock"), "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if token and marker.is_file() and marker.read_text(encoding="utf-8") == token:
            print(f"Extension already installed for this runner at {target}.", flush=True)
            return 0
        marker.unlink(missing_ok=True)
        result = run_process(
            [sys.executable, "-m", "pip", "install", "-U", "--target", str(target), str(source)], check=False,
        )
        if result.returncode == 0 and token:
            marker.write_text(token, encoding="utf-8")
        return result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    args = parser.parse_args()
    return install(args.target, os.environ.get(TOKEN_ENV) or None)


if __name__ == "__main__":
    raise SystemExit(main())
