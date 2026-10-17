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
    json.dumps({"patterns": ["["] , "names": ["JP"]}).encode(),
    json.dumps({"patterns": ["JP"] * 513, "names": []}).encode(),
    b" " * (8 * 1024 * 1024 + 1),
])
def test_worker_rejects_malformed_or_oversized_input_without_reflection(monkeypatch, payload):
    monkeypatch.setattr(resource, "setrlimit", lambda *args: None)
    output = _streams(monkeypatch, payload)
    assert regex_worker.main() == 2
    assert output.getvalue() == ""
