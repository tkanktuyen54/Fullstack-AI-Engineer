"""Small, deterministic checks around retrieved content and local LLM output.

These checks are conservative heuristics, not a proof of factual correctness.
"""

import re

from ..core.text import normalize
from ..retrieval.knowledge import terms

INSTRUCTION_PATTERNS = (
  r"(?:ignore|disregard|forget).{0,50}(?:previous|system|instructions)",
  r"bo qua.{0,50}(?:chi dan|huong dan|quy tac|lenh).{0,30}(?:truoc|he thong)",
  r"(?:reveal|print|show|hien thi|tiet lo|in ra).{0,50}(?:system prompt|api.key|mat khau|token bi mat)",
  r"<\|(?:im_start|im_end|system)\|>|\[/?INST\]",
)


def contains_instruction_override(text: str) -> bool:
  normalized = " ".join(normalize(text).split())
  return any(
    re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in INSTRUCTION_PATTERNS
  )


def compact(text: str) -> str:
  return " ".join(text.casefold().split())


def valid_fragment(answer: str, contexts: list) -> bool:
  """Check a whole-word prefix before publishing it; final evidence is checked separately."""
  if contains_instruction_override(answer):
    return False
  if re.search(r"https?://|www\.|<think>|</think>|<\|", answer, flags=re.IGNORECASE):
    return False
  content = " ".join(context["text"] for context in contexts)
  words = set(terms(answer))
  if words and len(words & set(terms(content))) / len(words) < 0.65:
    return False
  numbers = set(re.findall(r"\d+(?:[.,]\d+)*", answer))
  return numbers <= set(re.findall(r"\d+(?:[.,]\d+)*", content))


def valid_generation(answer: str, evidence: str, contexts: list, question: str = "") -> bool:
  if not answer.strip() or not evidence.strip() or contains_instruction_override(answer):
    return False
  if re.search(r"https?://|www\.|<think>|</think>|<\|", answer, flags=re.IGNORECASE):
    return False
  # Require a quote that really exists in the exact context the model received.
  quote = compact(evidence)
  if len(quote) < 15 or not any(quote in compact(context["text"]) for context in contexts):
    return False
  content = " ".join(context["text"] for context in contexts)
  if re.search(r"\b(?:bang|tables?)\b", normalize(question)):
    table_names = set(re.findall(r"\b(?:events|entities)\b", content, flags=re.IGNORECASE))
    if not all(
      re.search(r"\b" + name + r"\b", answer, flags=re.IGNORECASE) for name in table_names
    ):
      return False
  answer_words = set(terms(answer))
  content_words = set(terms(content))
  if not answer_words or len(answer_words & content_words) / len(answer_words) < 0.65:
    return False
  # Reject newly invented limits, prices, dates, URLs, etc.
  numbers = set(re.findall(r"\d+(?:[.,]\d+)*", answer))
  if not numbers <= set(re.findall(r"\d+(?:[.,]\d+)*", content)):
    return False
  return True
