import json
import logging
import sys

import pytest

from context_store.logger import clear_context, get_logger, set_context


def test_context_propagation(capsys):
    # ContextVar 経由で request_id や agent_id が伝播することを検証
    clear_context()
    set_context(request_id="req-123", agent_id="agent-456")
    logger = get_logger("test_context")
    logger.info("context test")
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["request_id"] == "req-123"
    assert output["agent_id"] == "agent-456"
    clear_context()


def test_structured_json_output(capsys):
    # 出力が JSON フォーマットであることを検証
    clear_context()
    logger = get_logger("test_structured")
    logger.info("hello structured logging")
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["level"] == "INFO"
    assert output["message"] == "hello structured logging"
    assert output["logger"] == "test_structured"


def test_stderr_fatal_errors(capsys):
    # 致命的エラーが stderr に出力されることを検証
    clear_context()
    logger = get_logger("test_stderr")
    logger.warning("this is a warning")
    captured = capsys.readouterr()
    # WARNING 以上は stderr に出力される
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["level"] == "WARNING"
    assert output["message"] == "this is a warning"
