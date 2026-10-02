# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Diagnostic logging: a full-screen UI cannot print, so failures go to a file."""

import logging

from azext_iot.adr.ui.core import diagnostics


def test_logging_is_off_without_a_path():
    assert diagnostics.configure(None) is None
    assert diagnostics.configure("") is None


def test_disabling_logging_closes_the_active_file(tmp_path):
    diagnostics.configure(str(tmp_path / "active.log"))
    diagnostics.configure(None)
    logger = logging.getLogger(diagnostics.LOGGER_NAME)
    assert not any(isinstance(handler, logging.FileHandler) for handler in logger.handlers)


def test_configure_writes_to_the_requested_file(tmp_path):
    target = tmp_path / "nested" / "radr.log"
    resolved = diagnostics.configure(str(target))
    try:
        diagnostics.log("queued creation: %s", "radar1")
        diagnostics.warn("something odd")
        logging.getLogger(diagnostics.LOGGER_NAME).handlers[-1].flush()
        contents = target.read_text(encoding="utf-8")
    finally:
        diagnostics.configure(None)
    assert resolved == str(target)
    assert "queued creation: radar1" in contents
    assert "something odd" in contents


def test_reconfiguring_does_not_stack_handlers(tmp_path):
    first, second = tmp_path / "a.log", tmp_path / "b.log"
    diagnostics.configure(str(first))
    diagnostics.configure(str(second))
    logger = logging.getLogger(diagnostics.LOGGER_NAME)
    file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1, "a re-run must not append to the previous file too"
    for handler in file_handlers:
        handler.close()
        logger.removeHandler(handler)


def test_default_path_sits_beside_the_cli_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(tmp_path))
    assert diagnostics.default_log_path() == str(tmp_path / "radr.log")
