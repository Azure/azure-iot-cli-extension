# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Download-only package probe using the pipeline's native feed authentication."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


FEED = "https://pkgs.dev.azure.com/azureiotdevxp/aziotcli/_packaging/pip/pypi/simple/"
PACKAGES = ("build", "wheel", "setuptools", "packaging")


def main():
    if os.environ.get("RELEASE_PIP_FEED_URL") != FEED:
        raise RuntimeError("The diagnostic requires the explicitly selected Azure Artifacts feed.")
    authenticated = os.environ.get("PIP_INDEX_URL", "")
    try:
        index = urlsplit(authenticated)
        port = index.port
    except ValueError:
        raise RuntimeError("PipAuthenticate did not provide a valid authenticated index URL.") from None
    feed = urlsplit(FEED)
    if (index.scheme != feed.scheme or index.hostname != feed.hostname
            or index.path.rstrip("/") != feed.path.rstrip("/")
            or not index.username or not index.password or port not in (None, 443)
            or index.query or index.fragment or any(character.isspace() for character in authenticated)):
        raise RuntimeError("PipAuthenticate must provide credentials for exactly the selected feed.")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PIP_")}
    environment.update(
        PIP_INDEX_URL=authenticated,
        PIP_CONFIG_FILE=os.devnull,
        PIP_EXTRA_INDEX_URL="",
        PIP_KEYRING_PROVIDER="disabled",
        PIP_NO_INPUT="1",
        PIP_DISABLE_PIP_VERSION_CHECK="1",
        PIP_NO_CACHE_DIR="1",
    )
    with tempfile.TemporaryDirectory(prefix="release-feed-probe-") as directory:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:",
             "--retries", "0", "--timeout", "30", "--dest", directory, *PACKAGES],
            env=environment, capture_output=True, text=True, timeout=300, check=False,
        )
        if result.returncode:
            output = result.stdout + "\n" + result.stderr
            diagnostics = [
                label for pattern, label in (
                    (r"\b401\b", "HTTP 401 authentication failure"),
                    (r"\b403\b", "HTTP 403 authorization failure"),
                    (r"\b404\b", "HTTP 404 feed or package not found"),
                    (r"(?i)timed out|timeout", "network timeout"),
                    (r"(?i)certificate|sslerror", "TLS validation failure"),
                    (r"(?i)no matching distribution", "no downloadable matching wheel"),
                ) if re.search(pattern, output)
            ]
            raise RuntimeError(f"Feed-only download failed with exit {result.returncode}: {diagnostics}. "
                               "Raw pip output is withheld to avoid exposing authenticated URLs.")
        wheels = sorted(path.name for path in Path(directory).iterdir())
        if len(wheels) != len(PACKAGES) or not all(name.endswith(".whl") for name in wheels):
            raise RuntimeError("The probe did not download exactly the four requested tooling wheels.")
        print(json.dumps({
            "result": "succeeded",
            "feed": FEED,
            "identity": "Pipeline Build Service via PipAuthenticate",
            "packages": wheels,
            "publicIndexFallback": False,
            "installedOrPublished": False,
        }))


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired:
        sys.exit("Feed-access diagnostic timed out; no token or raw subprocess output is emitted.")
    except RuntimeError as error:
        sys.exit(str(error))
