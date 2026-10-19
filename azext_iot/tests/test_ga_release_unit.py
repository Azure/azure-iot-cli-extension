# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import ast
from pathlib import Path

from packaging.requirements import Requirement
import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


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
