# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import subprocess
import sys
from types import SimpleNamespace

import pytest
from azure.cli.testsdk import LiveScenarioTest

from azext_iot.tests.conftest import pytest_pycollect_makeitem


@pytest.mark.parametrize("keyword,patterns,args", [
    ("_unit.py", ["test_*.py"], ["tests"]),
    ("", ["*_unit.py"], ["tests"]),
    ("", ["test_*_unit.py"], ["tests"]),
    ("", ["test_*.py"], ["tests/test_example_unit.py::test_example"]),
])
def test_unit_selectors_reject_live_scenario_classes_before_construction(keyword, patterns, args):
    config = SimpleNamespace(getoption=lambda _: keyword, getini=lambda _: patterns, args=args)
    collector = SimpleNamespace(config=config)

    class UnexpectedLiveScenario(LiveScenarioTest):
        __unittest_skip__ = False

        def __init__(self, *args, **kwargs):
            raise AssertionError("Live scenario constructor must not run")

    assert pytest_pycollect_makeitem(collector, "TestLive", UnexpectedLiveScenario) == []
    assert pytest_pycollect_makeitem(collector, "test_unit", lambda: None) is None


@pytest.mark.parametrize("keyword", ["", "not _unit.py", "_unit.py or _int.py"])
def test_safe_integration_manifest_collection_keeps_its_existing_collection_path(keyword):
    config = SimpleNamespace(getoption=lambda _: keyword, getini=lambda _: ["test_*.py"], args=["test_example_int.py"])
    assert pytest_pycollect_makeitem(SimpleNamespace(config=config), "LiveScenarioTest", LiveScenarioTest) is None


def test_real_pytest_collection_never_constructs_live_classes_in_unit_modules(tmp_path):
    module = tmp_path / "test_constructor_unit.py"
    module.write_text(
        "from azure.cli.testsdk import LiveScenarioTest\n"
        "class TestUnexpectedLiveScenario(LiveScenarioTest):\n"
        "    __unittest_skip__ = False\n"
        "    def __init__(self, *args, **kwargs):\n"
        "        raise RuntimeError('UNEXPECTED LIVE CONSTRUCTOR')\n"
        "    def test_live(self):\n"
        "        raise RuntimeError('UNEXPECTED LIVE TEST')\n"
        "def test_unit():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    script = f"""
import sys
sys.path[:0] = {sys.path!r}
import pytest
from azext_iot.tests.conftest import pytest_pycollect_makeitem
class Guard:
    pytest_pycollect_makeitem = staticmethod(pytest_pycollect_makeitem)
raise SystemExit(pytest.main([
    "-q", {str(module)!r}, "--rootdir", {str(tmp_path)!r}, "--confcutdir", {str(tmp_path)!r},
    "-o", "python_files=*_unit.py",
], plugins=[Guard()]))
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
