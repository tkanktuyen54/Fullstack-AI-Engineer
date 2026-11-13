"""Retrieve documentation, generate locally, then validate before publishing any answer."""

import logging
from contextlib import closing

from ..api.schemas import AdviceReply
from ..llm.ollama import InvalidGeneration, ModelBusy, ModelUnavailable
from .guardrails import contains_instruction_override, valid_fragment, valid_generation

logger = logging.getLogger(__name__)


class RagService:
  def __init__(self, knowledge, llm):
    self.knowledge = knowledge
    self.llm = llm

  def _prepare(self, request):
    if contains_instruction_override(request.message):
      return AdviceReply(
        message="Mình hỗ trợ hỏi đáp tài liệu CMC SecOps. Bạn hãy hỏi về tính năng hoặc cách sử dụng trong tài liệu.",
        intent="documentation",
        courses=[],
        engine="secops-guardrail",
        answerMode="blocked",
      ), []
    passages = [
      passage
      for passage in self.knowledge.retrieve(request)
      if not contains_instruction_override(passage["text"])
    ]
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
        "engine": "secops-bm25+ollama/" + self.llm.settings.model,
        "answerMode": "generated",
      }
    )

  @staticmethod
  def _fallback(fallback, error):
    reason = {
      ModelUnavailable: "model_unavailable",
      ModelBusy: "model_busy",
      InvalidGeneration: "invalid_generation",
    }[type(error)]
    logger.info("SecOps RAG uses an extractive answer: %s", reason)
    return fallback.model_copy(update={"fallbackReason": reason})

  def stream(self, request):
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
                "engine": "secops-bm25+ollama/" + self.llm.settings.model,
                "answerMode": "generated",
              }
            )
            yield {"type": "result", "reply": reply.model_dump(mode="json")}
            return
          pending += part.delta
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
