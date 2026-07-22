import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import metric_events


class _Response:
    def read(self):
        return b"ok"


def test_emit_metric_builds_eventbus_envelope(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(metric_events.urllib.request, "urlopen", fake_urlopen)

    metric_events.emit_metric(
        "metric://tests/result/query/summary",
        "test-suite",
        {"passed": 3},
        eventbus="http://events/",
    )

    request = captured["request"]
    assert request.full_url == "http://events/emit"
    assert request.headers["Content-type"] == "application/json"
    assert json.loads(request.data) == {
        "uri": "metric://tests/result/query/summary",
        "actor": "test-suite",
        "payload": {"passed": 3},
    }
    assert captured["timeout"] == 3


def test_emit_metric_ignores_eventbus_failure(monkeypatch):
    def fail(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(metric_events.urllib.request, "urlopen", fail)

    metric_events.emit_metric("metric://tests/result/query/summary", "tests", {})
