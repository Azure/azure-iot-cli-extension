# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Bounded release-environment diagnostics; never provision or publish resources."""

from importlib.metadata import distributions
import json
import os
from pathlib import Path
import re
import ssl
import sys


def inventory():
    selected = {
        "azure-cli", "azure-cli-core", "vsts-cd-manager", "mock", "pip",
        "setuptools", "wheel", "msal", "pymsalruntime",
    }
    packages, legacy_parents = [], []
    for package in distributions():
        name = package.metadata["Name"].lower().replace("_", "-")
        requirements = package.requires or []
        if name in selected:
            packages.append({
                "name": name, "version": package.version,
                "location": str(package.locate_file("")), "requirements": requirements,
            })
        if any(re.match(r"vsts[-_]cd[-_]manager(?:\W|$)", value, re.I) for value in requirements):
            legacy_parents.append({"name": name, "version": package.version, "requirements": requirements})
    print(json.dumps({
        "python": sys.version, "isolated": sys.flags.isolated,
        "pythonPathPresent": bool(os.environ.get("PYTHONPATH")),
        "packages": packages, "legacyParents": legacy_parents,
    }, indent=2), flush=True)


def tls():
    import requests

    url = "https://raw.githubusercontent.com/Azure/azure-cli/dev/scripts/ci/cmdcov.yml"
    system_bundle = Path("/etc/ssl/certs/ca-certificates.crt")
    if not system_bundle.is_file():
        raise RuntimeError("The trusted Ubuntu system CA bundle is missing.")
    context = ssl.create_default_context(cafile=str(system_bundle))
    print(json.dumps({
        "python": sys.version, "requestsBundle": requests.certs.where(),
        "systemBundle": str(system_bundle), "systemTrust": context.cert_store_stats(),
        "requestsBundleOverridePresent": bool(os.environ.get("REQUESTS_CA_BUNDLE")),
        "proxyConfigured": bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")),
    }), flush=True)
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.exceptions.SSLError:
        print("Default Requests trust failed certificate verification.", flush=True)
    else:
        print("Default Requests trust succeeded.", flush=True)
    response = requests.get(url, verify=str(system_bundle), timeout=30)
    response.raise_for_status()
    print("Explicit trusted system CA bundle succeeded.", flush=True)


if __name__ == "__main__":
    {"tls": tls, "inventory": inventory}[sys.argv[1]]()
