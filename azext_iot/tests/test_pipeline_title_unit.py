# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from pathlib import Path
import os
import runpy
import subprocess
import sys
from zipfile import ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[2]
TITLE = runpy.run_path(str(ROOT / "scripts/pipeline_title.py"))


@pytest.mark.parametrize("prefix,version,fields,expected", [
    ("iot", "1.0.1", {"scopes": ["ADU"], "regions": ["australiaeast"]},
     "iot-123 (1.0.1) (ADU) (australiaeast)"),
    ("ops", "2.11.2",
     {"scopes": ["edge"], "regions": ["westus2"], "runtimes": ["1.5.45"], "channels": ["stable"]},
     "ops-123 (2.11.2) (edge) (westus2) (runtime 1.5.45) (stable)"),
    ("ops", "2.11.2", {"action": "validate"}, "ops-123 (2.11.2) (validate)"),
    ("iot", None, {"scopes": ["ADU"], "regions": ["australiaeast"]}, "iot-123"),
    ("clean", None, {}, "clean-123"),
])
def test_title_orders_frozen_metadata_and_omits_inapplicable_groups(prefix, version, fields, expected):
    assert TITLE["format_title"](prefix, "123", version, **fields) == expected


def test_title_compacts_only_whole_scope_and_region_items():
    title = TITLE["format_title"](
        "iot", "123", "1.1.1b1", scopes=["ADR", "HubControl", "ADU", "DPS", "HubData"],
        regions=["westus2", "eastus2", "centralus", "australiaeast"],
    )
    assert title == "iot-123 (1.1.1b1) (DPS, Hub, ADU +1) (australiaeast, centralus, eastus2 +1)"


@pytest.mark.parametrize("fields", [
    {"version": "1.0.1]\n##vso[build.updatebuildnumber]other"},
    {"version": "1.0.1", "scopes": ["ADU) (other"]},
    {"version": "1.0.1", "regions": ["Australia East"]},
    {"version": "1.0.1", "channels": ["canary"]},
    {"version": "1.0.1", "action": "upload"},
])
def test_title_rejects_unsafe_or_unapproved_fields(fields):
    with pytest.raises(ValueError):
        TITLE["format_title"]("iot", "123", **fields)


@pytest.mark.parametrize("prefix", ["iot", "clean"])
def test_id_only_titles_still_enforce_the_ado_length_limit(prefix):
    with pytest.raises(ValueError, match="name limit"):
        TITLE["format_title"](prefix, "9" * 256)


def test_title_reads_exact_wheel_metadata_not_filename_or_host_version(tmp_path, monkeypatch):
    monkeypatch.setenv("BUILD_BUILDNUMBER", "old-name (99.0.0)")
    wheel = tmp_path / "candidate.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("azext_iot/__init__.py", "")
        archive.writestr("azure_iot-1.0.1.dist-info/METADATA", "Name: azure-iot\nVersion: 1.0.1\n")
    assert TITLE["wheel_version"](tmp_path) == "1.0.1"
    (tmp_path / "second.whl").write_bytes(wheel.read_bytes())
    with pytest.raises(ValueError, match="Exactly one"):
        TITLE["wheel_version"](tmp_path)


@pytest.mark.parametrize("prefix,distribution,package,valid", [
    ("iot", "azure-iot", "azext_iot", True),
    ("ops", "azure-iot", "azext_iot", False),
    ("iot", "azure-iot-ops", "azext_edge", False),
    ("iot", "azure-iot", "azext_edge", False),
    ("clean", "azure-iot", "azext_iot", False),
])
def test_title_cli_binds_product_prefix_to_wheel_identity(tmp_path, prefix, distribution, package, valid):
    wheel = tmp_path / "candidate.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr(package + "/__init__.py", "")
        archive.writestr("candidate.dist-info/METADATA", f"Name: {distribution}\nVersion: 1.2.3\n")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/pipeline_title.py"), "--prefix", prefix, "--wheel", str(wheel)],
        env={**os.environ, "BUILD_BUILDID": "123"}, text=True, capture_output=True, check=False,
    )
    if valid:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "##vso[build.updatebuildnumber]iot-123 (1.2.3)"
    else:
        assert result.returncode != 0
        assert "##vso[build.updatebuildnumber]" not in result.stdout
