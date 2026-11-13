"""Optionally phrase retrieved course advice; selection, prices and cards stay deterministic."""

from ..llm.ollama import InvalidGeneration, ModelBusy, ModelUnavailable
from .guardrails import contains_instruction_override, valid_generation
from .rag import RagService


def synthesize_courses(request, reply, llm):
  if not llm.settings.enabled:
    return reply.model_copy(update={"fallbackReason": "disabled"})
  if contains_instruction_override(request.message) or contains_instruction_override(reply.message):
    return reply
  contexts = [{"heading": "Kết quả tư vấn đã truy xuất", "text": reply.message[:500]}]
  remaining = 1400 - len(contexts[0]["text"])
  for course in reply.courses:
    text = f"{course.title}. Giá: {course.price} VND. Trình độ: {course.level}. {course.reason}"
    if contains_instruction_override(text):
      return reply
    text = text[: min(remaining, 300)]
    if text:
      contexts.append({"heading": course.title, "text": text})
      remaining -= len(text)
  try:
    result = llm.generate(request.message, contexts)
    if not valid_generation(result.answer, result.evidence, contexts):
      raise InvalidGeneration()
    # Names in the answer are also used by retrieval for follow-up questions.
    names = " · ".join(course.title for course in reply.courses)
    return reply.model_copy(
      update={
        "message": result.answer.strip() + ("\n" + names if names else ""),
        "engine": reply.engine + "+" + llm.provider + "/" + llm.settings.model,
        "answerMode": "generated",
      }
    )
  except (ModelUnavailable, ModelBusy, InvalidGeneration) as error:
    return RagService._fallback(reply, error)
