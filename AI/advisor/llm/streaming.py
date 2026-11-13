"""Decode only the answer field from an incomplete structured JSON response."""

import json


def string_prefix(text: str, start: int) -> str:
  if text[start] != '"':
    raise ValueError("answer must be a string")
  end = start + 1
  while end < len(text):
    char = text[end]
    if char == '"':
      value = json.loads(text[start : end + 1])
      if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError("Invalid Unicode in answer")
      return value
    if char == "\\":
      if end + 1 >= len(text):
        break
      width = 6 if text[end + 1] == "u" else 2
      if end + width > len(text):
        break
      end += width
    else:
      end += 1
  value = json.loads(text[start:end] + '"')
  # A UTF-16 pair may be split across model chunks. Do not publish a lone surrogate.
  if value and 0xD800 <= ord(value[-1]) <= 0xDBFF:
    value = value[:-1]
  if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
    raise ValueError("Invalid Unicode in answer")
  return value


def answer_prefix(text: str) -> str:
  decoder = json.JSONDecoder()
  position = len(text) - len(text.lstrip())
  if position >= len(text):
    return ""
  if text[position] != "{":
    raise ValueError("Expected a JSON object")
  position += 1
  while position < len(text):
    position += len(text[position:]) - len(text[position:].lstrip())
    try:
      key, position = decoder.raw_decode(text, position)
    except json.JSONDecodeError:
      return ""
    position += len(text[position:]) - len(text[position:].lstrip())
    if position >= len(text):
      return ""
    if text[position] != ":":
      raise ValueError("Expected a JSON property")
    position += 1
    position += len(text[position:]) - len(text[position:].lstrip())
    if position >= len(text):
      return ""
    if key == "answer":
      return string_prefix(text, position)
    try:
      _, position = decoder.raw_decode(text, position)
    except json.JSONDecodeError:
      return ""
    position += len(text[position:]) - len(text[position:].lstrip())
    if position >= len(text) or text[position] != ",":
      return ""
    position += 1
  return ""


class IncrementalAnswer:
  def __init__(self):
    self.content = ""
    self.emitted = ""

  def feed(self, fragment: str) -> str:
    self.content += fragment
    if len(self.content) > 32_000:
      raise ValueError("Generated JSON is too large")
    value = answer_prefix(self.content)
    if len(value) > 1600 or not value.startswith(self.emitted):
      raise ValueError("Invalid answer prefix")
    delta = value[len(self.emitted) :]
    self.emitted = value
    return delta
