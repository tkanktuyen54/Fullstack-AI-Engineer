import json
import threading
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from advisor.api.schemas import AdviceReply, AdviceRequest, ModelSelection, Suggestion
from advisor.app import create_app
from advisor.core.config import LlmSettings
from advisor.llm.groq import GroqClient
from advisor.llm.ollama import InvalidGeneration, ModelUnavailable
from advisor.retrieval.knowledge import DEFAULT_PATH, KnowledgeBase
from advisor.services.course_generation import synthesize_courses
from advisor.services.rag import RagService

ANSWER = "Threat Hunting cho phép chủ động truy vấn dữ liệu events và entities bằng SQL."
EVIDENCE = "chủ động truy vấn, khám phá dữ liệu"
KEY = "unit-test-groq-key"


def client(handler):
  return GroqClient(
    replace(LlmSettings(), model="openai/gpt-oss-20b"),
    KEY,
    threading.BoundedSemaphore(1),
    transport=httpx.MockTransport(handler),
  )


def completion(answer=ANSWER, evidence=EVIDENCE):
  return httpx.Response(
    200,
    json={
      "choices": [
        {
          "finish_reason": "stop",
          "message": {"content": json.dumps({"answer": answer, "evidence": evidence})},
        }
      ]
    },
  )


def sse(content=None, reason="stop", done=True):
  text = content or json.dumps({"answer": ANSWER, "evidence": EVIDENCE}, ensure_ascii=False)
  chunks = [
    {"choices": [{"delta": {"content": text[:30]}, "finish_reason": None}]},
    {"choices": [{"delta": {"content": text[30:]}, "finish_reason": None}]},
    {"choices": [{"delta": {}, "finish_reason": reason}]},
  ]
  body = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
  return httpx.Response(200, text=body + ("data: [DONE]\n\n" if done else ""))


def test_groq_uses_fixed_https_endpoint_bearer_key_and_json_mode():
  calls = []

  def handler(request):
    calls.append(request)
    return completion()

  llm = client(handler)
  try:
    reply = RagService(KnowledgeBase.load(DEFAULT_PATH), llm).answer(
      AdviceRequest(message="Threat Hunting là gì?", topic="secops")
    )
    assert reply.message == ANSWER and reply.answerMode == "generated"
    assert reply.engine == "secops-bm25+groq/openai/gpt-oss-20b"
    request = calls[0]
    assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer " + KEY
    body = json.loads(request.content)
    assert body["model"] == "openai/gpt-oss-20b"
    assert body["response_format"] == {"type": "json_object"}
    assert "think" not in body and "tools" not in body and KEY not in str(body)
    assert KEY not in reply.model_dump_json()
  finally:
    llm.close()


def test_groq_stream_emits_deltas_then_validated_result_and_releases_slot():
  llm = client(lambda request: sse())
  try:
    parts = list(llm.stream_generate("Threat Hunting?", []))
    assert "".join(part.delta for part in parts) == ANSWER
    assert parts[-1].result.answer == ANSWER
    assert llm.slot.acquire(blocking=False)
    llm.slot.release()
  finally:
    llm.close()


@pytest.mark.parametrize(
  "status,reason",
  [
    (401, "groq_authentication"),
    (429, "groq_rate_limited"),
    (500, "groq_service_unavailable"),
    (302, "groq_service_unavailable"),
  ],
)
def test_groq_failures_fall_back_without_leaking_provider_error_or_key(status, reason):
  calls = []

  def handler(request):
    calls.append(request)
    return httpx.Response(status, text=KEY, headers={"Location": "https://other.test"})

  llm = client(handler)
  try:
    events = list(
      RagService(KnowledgeBase.load(DEFAULT_PATH), llm).stream(
        AdviceRequest(message="Threat Hunting là gì?", topic="secops")
      )
    )
    assert events[-1]["reply"]["fallbackReason"] == reason
    assert KEY not in str(events) and len(calls) == 1
  finally:
    llm.close()


@pytest.mark.parametrize(
  "response",
  [
    sse(reason="length"),
    sse(done=False),
    sse(content="{}"),
    httpx.Response(200, json={"choices": []}),
  ],
)
def test_truncated_or_invalid_groq_stream_is_rejected(response):
  llm = client(lambda request: response)
  try:
    with pytest.raises(InvalidGeneration):
      list(llm.stream_generate("Question", []))
    assert llm.slot.acquire(blocking=False)
    llm.slot.release()
  finally:
    llm.close()


def test_groq_timeout_releases_slot():
  def handler(request):
    raise httpx.ReadTimeout("timeout", request=request)

  llm = client(handler)
  try:
    with pytest.raises(ModelUnavailable, match="groq_timeout"):
      llm.generate("Question", [])
    assert llm.slot.acquire(blocking=False)
    llm.slot.release()
  finally:
    llm.close()


def test_selection_secret_is_redacted_and_missing_key_is_rejected():
  selection = ModelSelection(provider="groq", model="test-model", apiKey=KEY)
  assert KEY not in repr(selection) and "apiKey" not in selection.model_dump()
  with pytest.raises(ValueError):
    ModelSelection(provider="groq", model="test-model")
  with pytest.raises(ValueError):
    ModelSelection(provider="local", model="test-cloud")


def test_course_generation_keeps_cards_and_rejects_invented_prices():
  original = AdviceReply(
    message="Khóa học Python cơ bản dành cho người mới bắt đầu.",
    intent="recommend",
    courses=[
      Suggestion(
        slug="python", title="Python cơ bản", price=499000, level="Cơ bản", reason="Học Python"
      )
    ],
    engine="tfidf",
  )
  request = AdviceRequest(message="Học Python")
  for answer, valid in [(original.message, True), ("Khóa học có giá 1 đồng.", False)]:
    llm = client(lambda req: completion(answer, original.message))
    try:
      reply = synthesize_courses(request, original, llm)
      assert reply.courses == original.courses
      assert (reply.answerMode == "generated") is valid
      if not valid:
        assert reply.message == original.message
    finally:
      llm.close()


def test_course_prompt_contains_retrieved_prices_and_descriptions():
  captured = []
  reply = AdviceReply(
    message="Đây là khóa học phù hợp.",
    intent="price",
    courses=[
      Suggestion(
        slug="python",
        title="Python cơ bản",
        price=499000,
        level="Cơ bản",
        reason="Học Python từ đầu.",
      )
    ],
    engine="tfidf",
  )

  def handler(request):
    captured.append(json.loads(request.content))
    return completion("Python cơ bản có giá 499000 VND.", "Python cơ bản. Giá: 499000 VND.")

  llm = client(handler)
  try:
    generated = synthesize_courses(AdviceRequest(message="Giá khóa Python?"), reply, llm)
    assert "499000" in captured[0]["messages"][1]["content"]
    assert generated.answerMode == "generated"
    assert generated.courses == reply.courses
  finally:
    llm.close()


def test_api_routes_groq_for_both_topics_without_mutating_local_client(monkeypatch):
  calls = []

  def factory(settings, api_key, slot):
    def handler(request):
      calls.append(json.loads(request.content))
      return sse() if calls[-1]["stream"] else completion()

    return GroqClient(settings, api_key, slot, transport=httpx.MockTransport(handler))

  monkeypatch.setattr("advisor.llm.selection.GroqClient", factory)
  with TestClient(create_app()) as http:
    for topic in ["courses", "secops"]:
      response = http.post(
        "/v1/advise",
        json={
          "message": "Threat Hunting là gì?",
          "topic": topic,
          "llm": {"provider": "groq", "model": "test-model", "apiKey": KEY},
        },
      )
      assert response.status_code == 200
      assert KEY not in response.text
    response = http.post(
      "/v1/advise/stream",
      json={
        "message": "Threat Hunting là gì?",
        "topic": "secops",
        "llm": {"provider": "groq", "model": "test-model", "apiKey": KEY},
      },
    )
    assert response.status_code == 200 and '"type": "delta"' in response.text
    assert "secops-bm25+groq/test-model" in response.text
    assert len(calls) == 3 and all(call["model"] == "test-model" for call in calls)
    assert http.app.state.llm.settings.model == "qwen3:0.6b"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
  "status,code,reason",
  [
    (400, "model_decommissioned", "groq_model_decommissioned"),
    (401, "invalid_api_key", "groq_authentication"),
    (403, "model_permission_blocked_org", "groq_permission_denied"),
    (404, "model_not_found", "groq_model_not_found"),
    (429, "rate_limit_exceeded", "groq_rate_limited"),
    (400, KEY, "groq_invalid_request"),
    (503, "server_error", "groq_service_unavailable"),
  ],
)
def test_groq_classifies_http_failures_and_never_echoes_raw_errors(
  monkeypatch, stream, status, code, reason
):
  logs = []
  monkeypatch.setattr(
    "advisor.llm.groq.log_event", lambda event, **fields: logs.append({"event": event, **fields})
  )
  body = json.dumps({"error": {"code": code, "message": KEY + " private prompt"}}).encode()
  llm = client(lambda request: httpx.Response(status, stream=httpx.ByteStream(body)))
  try:
    with pytest.raises(ModelUnavailable) as caught:
      if stream:
        list(llm.stream_generate("Question", []))
      else:
        llm.generate("Question", [])
    assert caught.value.reason == reason
    assert logs[-1]["status"] == status and logs[-1]["reason"] == reason
    assert KEY not in str(logs) and "private prompt" not in str(logs)
    assert llm.slot.acquire(blocking=False)
    llm.slot.release()
  finally:
    llm.close()


@pytest.mark.parametrize("model", ["openai/gpt-oss-20b", "openai/gpt-oss-120b"])
def test_gpt_oss_gets_reasoning_budget_and_excludes_reasoning_from_response(model):
  llm = client(lambda request: completion())
  llm.settings = replace(llm.settings, model=model)
  try:
    payload = llm._payload("Question", [], stream=True)
    assert payload["reasoning_effort"] == "low"
    assert payload["include_reasoning"] is False
    assert payload["max_completion_tokens"] == 1024
    assert "reasoning_format" not in payload
  finally:
    llm.close()


def test_connection_failures_are_distinct_from_api_errors():
  def handler(request):
    raise httpx.ConnectError("private network detail", request=request)

  llm = client(handler)
  try:
    with pytest.raises(ModelUnavailable, match="groq_connection_error"):
      list(llm.stream_generate("Question", []))
  finally:
    llm.close()


@pytest.mark.parametrize("stream", [False, True])
def test_only_numeric_usage_counts_are_logged(monkeypatch, stream):
  logs = []
  monkeypatch.setattr(
    "advisor.llm.groq.log_event", lambda event, **fields: logs.append({"event": event, **fields})
  )
  usage = {"prompt_tokens": 128, "completion_tokens": 64, "total_tokens": 192, "extra": KEY}

  def handler(request):
    if stream:
      body = sse().text.replace(
        "data: [DONE]", "data: " + json.dumps({"x_groq": {"usage": usage}}) + "\n\ndata: [DONE]"
      )
      return httpx.Response(200, text=body)
    data = json.loads(completion().content)
    return httpx.Response(200, json={**data, "usage": usage})

  llm = client(handler)
  try:
    if stream:
      list(llm.stream_generate("Question", []))
    else:
      llm.generate("Question", [])
    assert logs == [
      {
        "event": "llm_usage",
        "provider": "groq",
        "prompt_tokens": 128,
        "completion_tokens": 64,
        "total_tokens": 192,
      }
    ]
    assert KEY not in str(logs)
  finally:
    llm.close()
