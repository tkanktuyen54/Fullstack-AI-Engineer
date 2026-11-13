import asyncio
import json
import logging
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from advisor.api.middleware import OperationalMiddleware
from advisor.app import create_app
from advisor.core.config import AppSettings, LlmSettings
from advisor.core.telemetry import JsonFormatter, Telemetry
from advisor.llm.ollama import OllamaClient


@pytest.mark.parametrize(
  "name,value",
  [
    ("AI_ENVIRONMENT", "prod"),
    ("AI_STREAM_VALIDATION", "maybe"),
    ("AI_MAX_ACTIVE_REQUESTS", "0"),
    ("AI_MAX_ACTIVE_REQUESTS", "129"),
    ("AI_REQUIRE_KNOWLEDGE", "yes"),
    ("AI_READINESS_REQUIRE_LLM", "yes"),
  ],
)
def test_invalid_operational_configuration_is_rejected(monkeypatch, name, value):
  monkeypatch.setenv(name, value)
  with pytest.raises(ValueError):
    AppSettings.from_env()


def test_production_requires_token_and_defaults_to_complete_validation(monkeypatch):
  monkeypatch.setenv("AI_ENVIRONMENT", "production")
  monkeypatch.delenv("AI_SERVICE_TOKEN", raising=False)
  with pytest.raises(ValueError, match="AI_SERVICE_TOKEN"):
    with TestClient(create_app()):
      pytest.fail("Production started without authentication")
  monkeypatch.setenv("AI_SERVICE_TOKEN", "unit-test-production-token-123456789")
  settings = AppSettings.from_env()
  assert settings.stream_validation == "complete"
  assert settings.service_token not in repr(settings)


@pytest.fixture
def unavailable_model(monkeypatch):
  calls = []

  def handler(request):
    calls.append(request.url.path)
    return httpx.Response(503)

  llm = OllamaClient(LlmSettings(), transport=httpx.MockTransport(handler))
  monkeypatch.setattr("advisor.core.runtime.OllamaClient", lambda settings: llm)
  return calls


def test_liveness_has_no_upstream_io_and_readiness_allows_document_fallback(unavailable_model):
  with TestClient(create_app()) as client:
    assert client.get("/health/live").json() == {"status": "alive"}
    assert not unavailable_model
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"] == {"knowledge": True, "llm": False}


def test_readiness_can_require_llm(monkeypatch, unavailable_model):
  monkeypatch.setenv("AI_READINESS_REQUIRE_LLM", "true")
  with TestClient(create_app()) as client:
    assert client.get("/health/ready").status_code == 503
    assert client.get("/health/live").status_code == 200


def test_readiness_rejects_missing_required_knowledge(monkeypatch, tmp_path, unavailable_model):
  monkeypatch.setenv("AI_REQUIRE_KNOWLEDGE", "true")
  monkeypatch.setenv("AI_KNOWLEDGE_PATH", str(tmp_path / "missing.json"))
  with TestClient(create_app()) as client:
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert not response.json()["checks"]["knowledge"]


def test_metrics_auth_request_ids_and_bounded_route_labels(monkeypatch, unavailable_model):
  token = "unit-test-token"
  monkeypatch.setenv("AI_SERVICE_TOKEN", token)
  with TestClient(create_app()) as client:
    assert client.get("/metrics").status_code == 401
    response = client.post(
      "/v1/advise",
      headers={"X-Advisor-Token": token, "X-Request-ID": "be-request-123"},
      json={"message": "Threat Hunting là gì?", "topic": "secops"},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "be-request-123"
    assert response.json()["fallbackReason"] == "model_unavailable"
    invalid_id = client.get(
      "/does-not-exist/private-user-name", headers={"X-Request-ID": "x" * 100}
    )
    assert len(invalid_id.headers["X-Request-ID"]) == 32
    metrics = client.get("/metrics", headers={"X-Advisor-Token": token})
    assert metrics.status_code == 200
    assert "text/plain" in metrics.headers["Content-Type"]
    assert 'advisor_answers_total{mode="extractive",reason="model_unavailable"} 1.0' in metrics.text
    assert 'route="other"' in metrics.text
    assert "private-user-name" not in metrics.text
    assert "Threat Hunting" not in metrics.text and token not in metrics.text


def test_json_log_formatter_contains_only_explicit_operational_fields():
  record = logging.LogRecord("advisor", logging.INFO, "", 0, "rag_answer", (), None)
  record.fields = {"mode": "extractive", "reason": "model_busy"}
  data = json.loads(JsonFormatter().format(record))
  assert data["event"] == "rag_answer" and data["mode"] == "extractive"
  assert set(data) == {"timestamp", "level", "event", "requestId", "mode", "reason"}


def test_unexpected_http_error_is_sanitized_and_keeps_request_id(unavailable_model):
  app = create_app()

  @app.get("/test-error")
  def fail():
    raise RuntimeError("private-upstream-detail")

  with TestClient(app) as client:
    response = client.get("/test-error", headers={"X-Request-ID": "be-error-123"})
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "be-error-123"
    assert "private-upstream-detail" not in response.text
    metrics = client.get("/metrics").text
    assert 'advisor_http_requests_total{route="other",status="500"} 1.0' in metrics


def test_error_inside_stream_is_counted_even_with_http_200(unavailable_model):
  app = create_app()
  with TestClient(app) as client:

    def broken_stream(request):
      yield {"type": "status", "message": "Working"}
      raise RuntimeError("private-upstream-detail")

    app.state.rag.stream = broken_stream
    response = client.post("/v1/advise/stream", json={"message": "test", "topic": "secops"})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "error"
    assert "private-upstream-detail" not in response.text
    assert "advisor_stream_errors_total 1.0" in client.get("/metrics").text


def test_admission_limit_covers_stream_body_and_releases_on_cancellation():
  async def exercise():
    metrics = Telemetry()
    admission = threading.BoundedSemaphore(1)
    state = SimpleNamespace(telemetry=metrics, admission=admission)
    scope = {
      "type": "http",
      "path": "/v1/advise/stream",
      "method": "POST",
      "headers": [],
      "app": SimpleNamespace(state=state),
    }
    body_started = asyncio.Event()
    hold = asyncio.Event()

    async def downstream(scope, receive, send):
      await send({"type": "http.response.start", "status": 200, "headers": []})
      await send({"type": "http.response.body", "body": b"draft", "more_body": True})
      body_started.set()
      await hold.wait()
      await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def send(message):
      return None

    middleware = OperationalMiddleware(downstream)
    running = asyncio.create_task(middleware(scope, None, send))
    await body_started.wait()
    assert metrics.active._value.get() == 1
    # The first stream is still consuming capacity after its headers/draft were sent.
    second_response = []

    async def capture(message):
      second_response.append(message)

    await middleware(scope, None, capture)
    assert second_response[0]["status"] == 429
    assert metrics.active._value.get() == 1
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
      await running
    assert metrics.active._value.get() == 0
    assert admission.acquire(blocking=False)
    admission.release()
    assert 'status="incomplete"' in metrics.render().decode()

  asyncio.run(exercise())
