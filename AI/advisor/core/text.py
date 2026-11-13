"""Shared Vietnamese text normalization."""

import unicodedata


def normalize(text: str) -> str:
  text = unicodedata.normalize("NFD", str(text).lower().replace("đ", "d"))
  return "".join(char for char in text if unicodedata.category(char) != "Mn")
