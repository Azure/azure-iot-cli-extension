# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Read-only package download probe under an AzureCLI service-connection login."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote, urlsplit, urlunsplit


FEED = "https://pkgs.dev.azure.com/azureiotdevxp/aziotcli/_packaging/pip/pypi/simple/"
ADO_RESOURCE = "499b84ac-1321-427f-aa17-267ca6975798"
PACKAGES = ("build", "wheel", "setuptools", "packaging")


def main():
    if os.environ.get("RELEASE_PIP_FEED_URL") != FEED:
        raise RuntimeError("The diagnostic requires the explicitly selected Azure Artifacts feed.")
    identity = subprocess.run(
        ["az", "account", "show", "--query", "user.type", "--output", "tsv", "--only-show-errors"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if identity.returncode or identity.stdout.strip() != "servicePrincipal":
        raise RuntimeError("Expected the AzureCLI service-connection principal, not a user login.")
    response = subprocess.run(
        ["az", "account", "get-access-token", "--resource", ADO_RESOURCE,
         "--query", "accessToken", "--output", "tsv", "--only-show-errors"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if response.returncode:
        codes = sorted(set(re.findall(r"AADSTS[0-9]+", response.stderr)))
        raise RuntimeError(f"Azure DevOps token acquisition failed; Entra error codes: {codes}.")
    token = response.stdout.strip()
    if not token or any(character.isspace() for character in token):
        raise RuntimeError("Azure CLI did not return a valid single-line access token.")
    feed = urlsplit(FEED)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PIP_")}
    environment.update(
        PIP_INDEX_URL=urlunsplit((feed.scheme, f"build:{quote(token, safe='')}@{feed.netloc}",
                                 feed.path, "", "")),
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
            "identity": "AzureCLI service-connection principal",
            "tokenAudience": ADO_RESOURCE,
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
