import io
import json
import resource
import sys
from types import SimpleNamespace

import pytest
from decky_proxy import regex_worker


def _streams(monkeypatch, payload):
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(payload)))
    monkeypatch.setattr(sys, "stdout", output)
    return output


def test_worker_requires_linux_resource_limits_and_emits_only_bitsets(monkeypatch):
    limits = []
    monkeypatch.setattr(resource, "setrlimit", lambda kind, limit: limits.append((kind, limit)))
    monkeypatch.setattr(sys, "platform", "linux")
    output = _streams(monkeypatch, json.dumps({
        "patterns": ["JP`HK", "^(?:JP-)?[0-9]+$"], "names": ["JP", "HK", "12"],
    }).encode())
    assert regex_worker.main() == 0
    assert json.loads(output.getvalue()) == ["110", "001"]
    assert (resource.RLIMIT_CPU, (1, 1)) in limits
    assert (resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024)) in limits
    assert (resource.RLIMIT_CORE, (0, 0)) in limits


@pytest.mark.parametrize("payload", [b"invalid-json", b"{}", b'{"patterns":1,"names":[]}',
    json.dumps({"patterns": ["JP"] * 513, "names": []}).encode(),
    json.dumps({"patterns": "JP", "names": ["JP"]}).encode(),
    json.dumps({"patterns": ["JP"], "names": "JP"}).encode(),
    json.dumps({"patterns": [None], "names": ["JP"]}).encode(),
    json.dumps({"patterns": ["JP"], "names": [None]}).encode(),
    json.dumps({"patterns": ["a" * 16385], "names": ["JP"]}).encode(),
    json.dumps({"patterns": ["日" * 6000], "names": ["JP"]}).encode(),
    json.dumps({"patterns": ["JP\n"], "names": ["JP"]}).encode(),
    json.dumps({"patterns": ["JP"], "names": ["JP\n"]}).encode(),
    json.dumps({"patterns": ["JP"], "names": ["a" * 129]}).encode(),
    json.dumps({"patterns": ["JP"], "names": [""]}).encode(),
    json.dumps({"patterns": ["JP"], "names": ["JP"] * 2305}).encode(),
    b" " * (8 * 1024 * 1024 + 1),
])
def test_worker_rejects_malformed_or_oversized_input_without_reflection(monkeypatch, payload):
    monkeypatch.setattr(resource, "setrlimit", lambda *args: None)
    output = _streams(monkeypatch, payload)
    assert regex_worker.main() == 2
    assert output.getvalue() == ""


@pytest.mark.parametrize("pattern", ["[", "(?<=a+)JP", "(" * 1000 + "a" + ")" * 1000,
                                   "a{999999999999999999999}"])
def test_worker_reports_syntax_and_parser_limits_without_reflection(monkeypatch, pattern):
    monkeypatch.setattr(resource, "setrlimit", lambda *args: None)
    output = _streams(monkeypatch, json.dumps({"patterns": [pattern], "names": ["JP"]}).encode())
    assert regex_worker.main() == 3
    assert output.getvalue() == ""
