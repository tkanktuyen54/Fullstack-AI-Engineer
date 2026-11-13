"""Retrieve documentation, generate locally, then validate before publishing any answer."""

import time
from contextlib import closing

from ..api.schemas import AdviceReply
from ..core.telemetry import log_event
from ..llm.ollama import InvalidGeneration, ModelBusy, ModelUnavailable
from .guardrails import contains_instruction_override, valid_fragment, valid_generation


class RagService:
  def __init__(self, knowledge, llm, telemetry=None, stream_validation="incremental"):
    self.knowledge = knowledge
    self.llm = llm
    self.telemetry = telemetry
    self.stream_validation = stream_validation

  def _prepare(self, request):
    if contains_instruction_override(request.message):
      return AdviceReply(
        message="Mình hỗ trợ hỏi đáp tài liệu CMC SecOps. Bạn hãy hỏi về tính năng hoặc cách sử dụng trong tài liệu.",
        intent="documentation",
        courses=[],
        engine="secops-guardrail",
        answerMode="blocked",
      ), []
    started = time.monotonic()
    passages = [
      passage
      for passage in self.knowledge.retrieve(request)
      if not contains_instruction_override(passage["text"])
    ]
    if self.telemetry:
      self.telemetry.retrieval.observe(time.monotonic() - started)
    fallback = self.knowledge.answer(request, passages=passages)
    if not passages:
      return fallback, []
    if not self.llm.settings.enabled:
      return fallback.model_copy(update={"fallbackReason": "disabled"}), []
    # Keep prompts short for the 2K local context. History is used by retrieval, not sent in full.
    if len(request.message) > 800:
      return fallback.model_copy(update={"fallbackReason": "context_budget"}), []
    contexts = []
    remaining = 1400
    for passage in passages[:2]:
      text = passage["text"][: min(remaining, 1000)]
      if not text:
        break
      contexts.append({"heading": passage["heading"], "text": text})
      remaining -= len(text)
    return fallback, contexts

  def answer(self, request) -> AdviceReply:
    started = time.monotonic()
    reply = self._answer(request)
    self._record_reply(reply, started)
    if self.telemetry:
      self.telemetry.first_answer.observe(time.monotonic() - started)
    return reply

  def _answer(self, request) -> AdviceReply:
    fallback, contexts = self._prepare(request)
    if not contexts:
      return fallback
    try:
      result = self.llm.generate(request.message, contexts)
      if not valid_generation(result.answer, result.evidence, contexts, request.message):
        raise InvalidGeneration()
    except (ModelUnavailable, ModelBusy, InvalidGeneration) as error:
      return self._fallback(fallback, error)
    return fallback.model_copy(
      update={
        "message": result.answer.strip(),
        "engine": self._engine(),
        "answerMode": "generated",
      }
    )

  @staticmethod
  def _fallback(fallback, error):
    reason = (
      error.reason
      if isinstance(error, ModelUnavailable)
      else {ModelBusy: "model_busy", InvalidGeneration: "invalid_generation"}[type(error)]
    )
    return fallback.model_copy(update={"fallbackReason": reason})

  def _engine(self):
    return "secops-bm25+" + self.llm.provider + "/" + self.llm.settings.model

  def stream(self, request):
    started = time.monotonic()
    published = False
    with closing(self._stream(request)) as events:
      for event in events:
        if event["type"] in ("delta", "result") and not published:
          published = True
          if self.telemetry:
            self.telemetry.first_answer.observe(time.monotonic() - started)
        if event["type"] == "result":
          self._record_reply(AdviceReply.model_validate(event["reply"]), started)
        yield event

  def _record_reply(self, reply, started):
    if self.telemetry:
      self.telemetry.record_reply(reply)
    log_event(
      "rag_answer",
      mode=reply.answerMode,
      reason=reply.fallbackReason or "none",
      seconds=round(time.monotonic() - started, 4),
    )

  def _stream(self, request):
    yield {"type": "status", "message": "Đang tìm thông tin trong tài liệu…"}
    fallback, contexts = self._prepare(request)
    if not contexts:
      yield {"type": "result", "reply": fallback.model_dump(mode="json")}
      return
    yield {"type": "status", "message": "Đang tạo câu trả lời từ tài liệu…"}
    pending = ""
    emitted = ""
    try:
      with closing(self.llm.stream_generate(request.message, contexts)) as generation:
        for part in generation:
          if part.result is not None:
            result = part.result
            yield {"type": "status", "message": "Đang đối chiếu câu trả lời với nguồn…"}
            if not valid_generation(result.answer, result.evidence, contexts, request.message):
              raise InvalidGeneration()
            if pending:
              yield {"type": "delta", "text": pending}
            reply = fallback.model_copy(
              update={
                "message": result.answer.strip(),
                "engine": self._engine(),
                "answerMode": "generated",
              }
            )
            yield {"type": "result", "reply": reply.model_dump(mode="json")}
            return
          pending += part.delta
          # Production can withhold all draft text until the final checks pass.
          if self.stream_validation == "complete":
            continue
          # Publish short whole-word fragments, not a simulated typewriter after generation.
          while len(pending) >= 32:
            end = pending.rfind(" ", 0, 33)
            if end < 0:
              break
            fragment = pending[: end + 1]
            pending = pending[end + 1 :]
            if not valid_fragment(emitted + fragment, contexts):
              raise InvalidGeneration()
            emitted += fragment
            yield {"type": "delta", "text": fragment}
      raise InvalidGeneration()
    except (ModelUnavailable, ModelBusy, InvalidGeneration) as error:
      reply = self._fallback(fallback, error)
      # Final result replaces any provisional text already displayed by the browser.
      yield {"type": "result", "reply": reply.model_dump(mode="json")}
