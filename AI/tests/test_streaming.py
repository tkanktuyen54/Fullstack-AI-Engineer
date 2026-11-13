import json

import httpx
import pytest
from fastapi.testclient import TestClient

from advisor.api.schemas import AdviceRequest
from advisor.app import app
from advisor.core.config import LlmSettings
from advisor.llm.ollama import InvalidGeneration, OllamaClient
from advisor.llm.streaming import IncrementalAnswer
from advisor.retrieval.knowledge import DEFAULT_PATH, KnowledgeBase
from advisor.services.rag import RagService

ANSWER = "Threat Hunting cho phép chủ động truy vấn dữ liệu events và entities bằng SQL."
EVIDENCE = "chủ động truy vấn, khám phá dữ liệu"


class ModelStream(httpx.SyncByteStream):
  def __init__(self, content, done=True, reason="stop"):
    self.content = content
    self.done = done
    self.reason = reason
    self.closed = False
    self.finished = False

  def __iter__(self):
    # Thinking is deliberately ignored, even if a provider sends it.
    yield b'{"message":{"thinking":"PRIVATE_TRACE"},"done":false}\n'
    for char in self.content:
      yield (
        json.dumps({"message": {"content": char}, "done": False}, ensure_ascii=False) + "\n"
      ).encode()
    if self.done:
      yield (json.dumps({"done": True, "done_reason": self.reason}) + "\n").encode()
    self.finished = True

  def close(self):
    self.closed = True


def client_for(stream, captured=None):
  def handler(request):
    if captured is not None:
      captured.append(json.loads(request.content))
    return httpx.Response(200, headers={"Content-Type": "application/x-ndjson"}, stream=stream)

  return OllamaClient(LlmSettings(), transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("ensure_ascii", [True, False])
@pytest.mark.parametrize("answer_first", [True, False])
def test_incremental_decoder_handles_utf8_escapes_and_either_property_order(
  ensure_ascii, answer_first
):
  answer = 'Tiếng Việt: "xin chào"\nDòng mới 😀 \\ ví dụ'
  body = {"answer": answer, "evidence": "Không đưa evidence ra giao diện"}
  if not answer_first:
    body = dict(reversed(list(body.items())))
  decoder = IncrementalAnswer()
  output = ""
  for char in json.dumps(body, ensure_ascii=ensure_ascii):
    output += decoder.feed(char)
  assert output == answer
  assert "evidence" not in output


def test_model_yields_answer_before_finishing_and_cancellation_closes_resources():
  stream = ModelStream(json.dumps({"answer": ANSWER, "evidence": EVIDENCE}))
  captured = []
  llm = client_for(stream, captured)
  generation = llm.stream_generate("Threat Hunting là gì?", [{"text": ANSWER}])
  try:
    first = next(generation)
    assert first.delta and first.result is None
    assert not stream.finished
    assert captured[0]["stream"] is True
    assert captured[0]["think"] is False
  finally:
    generation.close()
    assert stream.closed
    assert llm.slot.acquire(blocking=False)
    llm.slot.release()
    llm.close()


def test_rag_publishes_multiple_deltas_then_an_authoritative_result():
  stream = ModelStream(json.dumps({"answer": ANSWER, "evidence": EVIDENCE}))
  llm = client_for(stream)
  rag = RagService(KnowledgeBase.load(DEFAULT_PATH), llm)
  try:
    events = list(rag.stream(AdviceRequest(message="Threat Hunting là gì?", topic="secops")))
    deltas = [event["text"] for event in events if event["type"] == "delta"]
    assert len(deltas) >= 2
    assert "".join(deltas) == ANSWER
    assert events[-1]["type"] == "result"
    assert events[-1]["reply"]["message"] == ANSWER
    assert events[-1]["reply"]["answerMode"] == "generated"
    assert "PRIVATE_TRACE" not in json.dumps(events)
    assert EVIDENCE not in "".join(deltas)
  finally:
    llm.close()


@pytest.mark.parametrize(
  "done, reason, evidence",
  [
    (False, "stop", EVIDENCE),
    (True, "length", EVIDENCE),
    (True, "stop", "Bằng chứng không có trong nguồn"),
  ],
)
def test_final_validation_failure_replaces_provisional_text_with_source(done, reason, evidence):
  stream = ModelStream(
    json.dumps({"answer": ANSWER, "evidence": evidence}), done=done, reason=reason
  )
  llm = client_for(stream)
  try:
    events = list(
      RagService(KnowledgeBase.load(DEFAULT_PATH), llm).stream(
        AdviceRequest(message="Threat Hunting là gì?", topic="secops")
      )
    )
    assert any(event["type"] == "delta" for event in events)
    reply = events[-1]["reply"]
    assert reply["answerMode"] == "extractive"
    assert reply["fallbackReason"] == "invalid_generation"
    assert reply["message"].startswith("Theo tài liệu CMC SecOps")
    assert stream.closed
  finally:
    llm.close()


def test_unsafe_prefix_is_never_forwarded():
  answer = "9999 ngày lưu trữ dữ liệu Threat Hunting."
  stream = ModelStream(json.dumps({"answer": answer, "evidence": EVIDENCE}))
  llm = client_for(stream)
  try:
    events = list(
      RagService(KnowledgeBase.load(DEFAULT_PATH), llm).stream(
        AdviceRequest(message="Threat Hunting là gì?", topic="secops")
      )
    )
    assert not any(event["type"] == "delta" for event in events)
    assert events[-1]["reply"]["answerMode"] == "extractive"
  finally:
    llm.close()


def test_stream_without_completion_is_invalid_and_releases_slot():
  stream = ModelStream('{"answer":"incomplete', done=False)
  llm = client_for(stream)
  try:
    with pytest.raises(InvalidGeneration):
      list(llm.stream_generate("Question", []))
    assert stream.closed
    assert llm.slot.acquire(blocking=False)
    llm.slot.release()
  finally:
    llm.close()


def test_decoder_rejects_lone_surrogates_and_oversized_answers():
  with pytest.raises(ValueError):
    IncrementalAnswer().feed('{"answer":"\\ud800"}')
  with pytest.raises(ValueError):
    IncrementalAnswer().feed(json.dumps({"answer": "x" * 1601}))


def test_stream_route_authenticates_before_headers_and_returns_json_lines(monkeypatch):
  stream = ModelStream(json.dumps({"answer": ANSWER, "evidence": EVIDENCE}))
  llm = client_for(stream)
  monkeypatch.setenv("AI_SERVICE_TOKEN", "test-secret")
  monkeypatch.setattr("advisor.core.runtime.OllamaClient", lambda settings: llm)
  with TestClient(app) as client:
    body = {"message": "Threat Hunting là gì?", "topic": "secops"}
    assert client.post("/v1/advise/stream", json=body).status_code == 401
    response = client.post(
      "/v1/advise/stream", json=body, headers={"X-Advisor-Token": "test-secret"}
    )
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines()]
    assert any(event["type"] == "delta" for event in events)
    assert events[-1]["reply"]["message"] == ANSWER
