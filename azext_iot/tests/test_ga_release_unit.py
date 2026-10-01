# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import ast
import os
from pathlib import Path
import shutil
import subprocess

from packaging.requirements import Requirement
import pytest
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["github", "ado"])
def macos_openssl_step(request):
    if request.param == "github":
        workflow = yaml.safe_load((REPOSITORY_ROOT / ".github/workflows/tox.yml").read_text(encoding="utf-8"))
        steps = workflow["jobs"]["tox"]["steps"]
        selected = next(step for step in steps if step.get("name") == "Select OpenSSL 3 for CSR signing")
        assert steps.index(selected) < next(i for i, step in enumerate(steps) if step.get("name") == "Setup test suite")
    else:
        template = yaml.safe_load(
            (REPOSITORY_ROOT / ".azure-devops/templates/setup-dev-test-env.yml").read_text(encoding="utf-8")
        )
        steps = template["steps"]
        selected = next(step for step in steps if step.get("displayName") == "Select OpenSSL 3 for CSR signing")
        assert steps.index(selected) < next(
            i for i, step in enumerate(steps) if step.get("template") == "download-install-local-azure-iot-cli-extension.yml"
        )
    return request.param, selected


def test_native_openssl_selection_is_scoped_to_macos(macos_openssl_step):
    provider, step = macos_openssl_step
    if provider == "github":
        assert step["if"] == "runner.os == 'macOS'"
        assert step["shell"] == "bash"
        script = step["run"]
    else:
        assert step["condition"] == "and(succeeded(), eq(variables['Agent.OS'], 'Darwin'))"
        script = step["bash"]
    assert "source scripts/select-openssl.sh" in script


@pytest.mark.skipif(os.name != "posix", reason="The macOS dependency-selection step requires a POSIX shell.")
@pytest.mark.parametrize("capability", ["ready", "missing", "unsupported"])
def test_native_openssl_selection_proves_capabilities_before_changing_path(macos_openssl_step, tmp_path, capability):
    provider, step = macos_openssl_step
    bash, openssl = shutil.which("bash"), shutil.which("openssl")
    assert bash and openssl
    prefix = Path(openssl).resolve().parents[1]
    if capability != "ready":
        prefix = tmp_path / "openssl"
        if capability == "unsupported":
            binary = prefix / "bin" / "openssl"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\nprintf 'OpenSSL without required signing options\\n'\n", encoding="utf-8")
            binary.chmod(0o700)
    output = tmp_path / "github-path"
    brew = """
brew() {
  test "$#" -eq 2
  test "$1" = --prefix
  test "$2" = openssl@3
  printf '%s\\n' "$OPENSSL_PREFIX"
}
"""
    result = subprocess.run(
        [bash, "-c", brew + (step["run"] if provider == "github" else step["bash"])],
        cwd=REPOSITORY_ROOT,
        env=dict(os.environ, OPENSSL_PREFIX=str(prefix), GITHUB_PATH=str(output)),
        capture_output=True, text=True, timeout=20, check=False,
    )
    ado_path = f"##vso[task.prependpath]{prefix / 'bin'}"
    if capability == "ready":
        assert result.returncode == 0, result.stdout + result.stderr
        if provider == "github":
            assert output.read_text(encoding="utf-8") == str(prefix / "bin") + "\n"
            assert ado_path not in result.stdout
        else:
            assert ado_path in result.stdout.splitlines()
            assert not output.exists()
    else:
        assert result.returncode != 0
        assert not output.exists()
        assert "##vso[task.prependpath]" not in result.stdout


def test_ado_style_check_installs_cli_in_selected_python():
    workflow = yaml.safe_load((REPOSITORY_ROOT / ".azure-devops/merge.yml").read_text(encoding="utf-8"))
    steps = next(job for job in workflow["jobs"] if job["job"] == "run_style_check")["steps"]
    templates = [step.get("template") for step in steps]
    setup = templates.index("templates/setup-python.yml")
    cli = templates.index("templates/install-azure-cli-released.yml")
    extension = templates.index("templates/download-install-local-azure-iot-cli-extension-with-pip.yml")
    pylint = next(index for index, step in enumerate(steps) if step.get("script", "").startswith("pylint "))
    assert setup < cli < extension < pylint
    install = yaml.safe_load(
        (REPOSITORY_ROOT / ".azure-devops/templates/install-azure-cli-released.yml").read_text(encoding="utf-8")
    )
    assert install["steps"][0]["script"] == "python -m pip install azure-cli"


@pytest.mark.parametrize("name,minimum", [
    ("azure-core", "1.37.0"), ("azure-mgmt-core", "1.6.0"),
    ("isodate", "0.6.1"), ("typing-extensions", "4.6.0"),
])
def test_dependency_floors_match_generated_sdk_requirements(name, minimum):
    tree = ast.parse((REPOSITORY_ROOT / "setup.py").read_text(encoding="utf-8"))
    dependencies = next(
        ast.literal_eval(node.value) for node in tree.body
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DEPENDENCIES" for target in node.targets
        )
    )
    requirement = next(Requirement(value) for value in dependencies if Requirement(value).name == name)
    assert any(spec.operator == ">=" and spec.version == minimum for spec in requirement.specifier)
