"""Resolve a request's provider without changing other sessions' model or credentials."""

from contextlib import contextmanager
from dataclasses import replace

from .groq import GroqClient
from .ollama import OllamaClient


@contextmanager
def selected_llm(state, request):
  selection = request.llm
  if selection is None or (
    selection.provider == "local" and selection.model == state.llm.settings.model
  ):
    yield state.llm
    return
  settings = replace(state.llm.settings, model=selection.model)
  if selection.provider == "groq":
    llm = GroqClient(
      replace(settings, enabled=True), selection.apiKey.get_secret_value(), state.groq_slot
    )
  else:
    llm = OllamaClient(settings)
    llm.slot = state.llm.slot
  try:
    yield llm
  finally:
    llm.close()
