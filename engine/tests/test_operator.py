"""Operator CLI request journal and retry protocol."""

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from uuid import UUID

import pytest

from arena_engine import operator_cli
from arena_engine.contract import canonical_bytes
from arena_engine.runtime import Settings, DEFAULT_IMAGE


TOKEN = "operator-secret-must-not-enter-journal"


def cli(tmp_path):
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    operator_cli.parser(commands)
    state = tmp_path / "runtime"
    auth = state / "auth"
    auth.mkdir(parents=True)
    token_path = auth / "operator.token"
    token_path.write_text(TOKEN + "\n")
    os.chmod(token_path, 0o600)
    return root, Settings(state, DEFAULT_IMAGE)


class Response:
    def __init__(self, body=b'{"ok":true}'):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def test_transport_failure_journals_before_send_and_retry_reuses_exact_request(tmp_path, monkeypatch, capsys):
    root, settings = cli(tmp_path)
    args = root.parse_args(["operator", "create", "--label-a", "A", "--label-b", "B"])
    sent = []

    def fail(request, timeout):
        journal = next((settings.state_dir / "operator-requests").glob("*.json"))
        request_id = journal.stem
        UUID(request_id)
        assert journal.is_file(), "journal must be durable before transport starts"
        record = json.loads(journal.read_text())
        assert journal.read_bytes() == canonical_bytes(record)
        assert request.data == canonical_bytes(record["body"])
        assert TOKEN not in journal.read_text()
        sent.append((request.full_url, request.data, request.headers["Authorization"], timeout, request_id))
        raise URLError("synthetic offline transport")

    monkeypatch.setattr(operator_cli, "urlopen", fail)
    assert operator_cli.run(args, settings) == 1
    stderr = capsys.readouterr().err
    request_id = sent[0][4]
    assert UUID(request_id)
    assert "request_id=" + request_id in stderr
    journal_path = settings.state_dir / "operator-requests" / (request_id + ".json")
    mode = journal_path.stat().st_mode & 0o777
    assert mode == 0o600
    original = json.loads(journal_path.read_text())

    retry = root.parse_args(["operator", "retry", "--request-id", request_id])

    def succeed(request, timeout):
        sent.append((request.full_url, request.data, request.headers["Authorization"], timeout, request_id))
        return Response()

    monkeypatch.setattr(operator_cli, "urlopen", succeed)
    assert operator_cli.run(retry, settings) == 0
    assert sent[0][1] == sent[1][1] == canonical_bytes(original["body"])
    assert sent[0][0] == sent[1][0] == "http://127.0.0.1:8765/api/v1" + original["endpoint"]
    assert sent[0][2] == sent[1][2] == "Bearer " + TOKEN
    assert sent[0][4] == sent[1][4] == request_id
    assert capsys.readouterr().out.strip() == '{"ok":true}'


def test_same_request_id_for_different_operation_is_refused_locally(tmp_path, monkeypatch, capsys):
    root, settings = cli(tmp_path)
    request_id = "0b63938d-809f-4f74-8d3e-f909ccf87af1"
    create = root.parse_args(["operator", "create", "--request-id", request_id])
    calls = []

    def offline(request, timeout):
        calls.append(request)
        raise URLError("offline")

    monkeypatch.setattr(operator_cli, "urlopen", offline)
    assert operator_cli.run(create, settings) == 1
    action = root.parse_args(["operator", "action", "--match", "m1", "--action", "cancel",
                              "--reason", "stop", "--request-id", request_id])
    with pytest.raises(ValueError, match="different operation/body"):
        operator_cli.run(action, settings)
    assert len(calls) == 1
    capsys.readouterr()


def test_http_error_is_json_stdout_with_failure_exit_code(tmp_path, monkeypatch, capsys):
    root, settings = cli(tmp_path)
    action = root.parse_args(["operator", "action", "--match", "match-1", "--action", "reveal",
                              "--reason", "ready"])
    payload = b'{"error":{"code":"INVALID_STATE","message":"not ready","details":{}}}'

    def reject(_request, timeout):
        raise HTTPError("http://localhost", 409, "Conflict", {}, __import__("io").BytesIO(payload))

    monkeypatch.setattr(operator_cli, "urlopen", reject)
    assert operator_cli.run(action, settings) == 1
    captured = capsys.readouterr()
    assert captured.out == payload.decode() + "\n"
    assert "request_id=" in captured.err
