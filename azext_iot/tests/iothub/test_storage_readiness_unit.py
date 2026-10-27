# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cli.core.azclierror import BadRequestError, CLIInternalError
from azure.core.exceptions import ServiceResponseError

from azext_iot.tests.iothub import _integration_helpers as helpers


@pytest.fixture
def readiness(mocker):
    clock = [0]
    sleeps = []
    attempts = []
    mocker.patch.object(helpers, "monotonic", side_effect=lambda: clock[0])
    mocker.patch.object(
        helpers, "sleep", side_effect=lambda seconds: (sleeps.append(seconds), clock.__setitem__(0, clock[0] + seconds)),
    )

    @contextmanager
    def scope(*args):
        attempt = {"rejected": False, "correlationId": "offline"}
        attempts.append((args, attempt))
        yield attempt

    observer = SimpleNamespace(storage_endpoint_attempt=scope)
    return SimpleNamespace(
        helper=helpers.StorageEndpointReadiness(observer, "hub", "storage", "container"),
        clock=clock, sleeps=sleeps, attempts=attempts,
    )


def run(readiness, invoke, endpoint="endpoint", identity="[system]"):
    return readiness.helper.invoke(invoke, "exact original command", endpoint=endpoint, identity=identity)


def test_immediate_readiness_success_does_not_sleep_or_repeat(readiness):
    invoke = Mock(return_value="output")
    assert run(readiness, invoke) == "output"
    invoke.assert_called_once_with("exact original command")
    assert readiness.sleeps == []
    assert readiness.attempts[0][0] == ("hub", "storage", "endpoint", "container", "[system]", 600)


def test_only_proven_rejections_wait_and_then_return_real_success(readiness):
    calls = []

    def invoke(command):
        calls.append(command)
        readiness.clock[0] += 5
        if len(calls) < 3:
            readiness.attempts[-1][1]["rejected"] = True
            raise BadRequestError("proven permission rejection")
        return "real success"

    assert run(readiness, invoke) == "real success"
    assert calls == ["exact original command"] * 3
    assert readiness.sleeps == [30, 30]
    assert readiness.clock[0] == 75


def test_deadline_charges_calls_clips_sleep_and_preserves_last_error(readiness):
    error = BadRequestError("proven rejection")

    def invoke(_command):
        readiness.attempts[-1][1]["rejected"] = True
        readiness.clock[0] += 595
        raise error

    with pytest.raises(CLIInternalError, match="600-second budget") as raised:
        run(readiness, invoke)
    assert raised.value.__cause__ is error
    assert readiness.sleeps == [5]
    assert len(readiness.attempts) == 1


def test_slow_failed_rpc_cannot_extend_deadline(readiness):
    def invoke(_command):
        readiness.attempts[-1][1]["rejected"] = True
        readiness.clock[0] += 601
        raise BadRequestError("proven rejection")

    with pytest.raises(CLIInternalError):
        run(readiness, invoke)
    assert readiness.sleeps == []
    assert len(readiness.attempts) == 1


def test_system_and_user_identity_share_one_budget(readiness):
    assert run(readiness, Mock(return_value="system success")) == "system success"
    readiness.clock[0] = 600
    invoke = Mock()
    with pytest.raises(CLIInternalError):
        run(readiness, invoke, endpoint="other", identity="user-identity")
    invoke.assert_not_called()
    assert len(readiness.attempts) == 1


@pytest.mark.parametrize("elapsed", [600, 601])
def test_late_success_preserves_observer_completion_without_replaying(readiness, elapsed, caplog):
    completed = []

    @contextmanager
    def observe(*_args):
        yield {"rejected": False, "correlationId": "offline"}
        completed.append("mutation recorded")

    readiness.helper.observer.storage_endpoint_attempt = observe

    def invoke(_command):
        readiness.clock[0] = elapsed
        return "successful mutation"

    command = Mock(side_effect=invoke)
    with pytest.raises(CLIInternalError, match="successful mutation will not be replayed"):
        run(readiness, command)
    assert completed == ["mutation recorded"]
    command.assert_called_once()
    assert readiness.sleeps == []
    assert "Storage endpoint ready" not in caplog.text


@pytest.mark.parametrize("error", [
    BadRequestError("IH400117 alone is insufficient"),
    CLIInternalError("nonzero exit"),
    ServiceResponseError("Connection reset"),
    AssertionError("wrong endpoint"),
])
def test_unproven_errors_fail_without_sleep_or_replay(readiness, error):
    invoke = Mock(side_effect=error)
    with pytest.raises(type(error)) as raised:
        run(readiness, invoke)
    assert raised.value is error
    invoke.assert_called_once()
    assert readiness.sleeps == []


def test_unmanaged_invocation_cannot_use_readiness_retries():
    helper = helpers.StorageEndpointReadiness(None, None, "storage", "container")
    error = BadRequestError("IH400117")
    invoke = Mock(side_effect=error)
    with pytest.raises(BadRequestError) as raised:
        helper.invoke(invoke, "command", endpoint="ep", identity="[system]")
    assert raised.value is error
    invoke.assert_called_once()
