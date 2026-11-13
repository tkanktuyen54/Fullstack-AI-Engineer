"""Groq chat completions with bounded output and no credentials in replies or logs."""

import json
import time

import httpx

from ..core.telemetry import log_event
from .ollama import (
  GenerationChunk,
  GroundedAnswer,
  InvalidGeneration,
  ModelBusy,
  ModelUnavailable,
  OllamaClient,
)
from .streaming import IncrementalAnswer


class GroqClient(OllamaClient):
  provider = "groq"

  def __init__(self, settings, api_key, slot, transport=None):
    self.settings = settings
    self.slot = slot
    self.http = httpx.Client(
      base_url="https://api.groq.com/openai/v1/",
      headers={"Authorization": "Bearer " + api_key},
      timeout=httpx.Timeout(settings.timeout_seconds, connect=3),
      follow_redirects=False,
      trust_env=False,
      transport=transport,
    )

  def _payload(self, question: str, contexts: list, stream=False) -> dict:
    messages = super()._payload(question, contexts)["messages"]
    payload = {
      "model": self.settings.model,
      "messages": messages,
      "response_format": {"type": "json_object"},
      "temperature": 0,
      "max_completion_tokens": self.settings.max_output_tokens,
      "stream": stream,
    }
    # GPT-OSS needs a budget for reasoning as well as the final JSON answer.
    if self.settings.model in ("openai/gpt-oss-20b", "openai/gpt-oss-120b"):
      payload.update(
        reasoning_effort="low",
        include_reasoning=False,
        max_completion_tokens=max(1024, self.settings.max_output_tokens),
      )
    elif self.settings.model == "qwen/qwen3.8-27b":
      payload.update(reasoning_effort="none", reasoning_format="hidden")
    return payload

  def _failure(self, error=None, status=None, code=None):
    # Only allow known codes. Never log upstream messages, bodies, prompts or credentials.
    known_codes = {
      "model_decommissioned",
      "model_not_found",
      "invalid_api_key",
      "model_permission_blocked_org",
      "model_permission_blocked_project",
      "json_validate_failed",
      "rate_limit_exceeded",
    }
    if isinstance(error, httpx.HTTPStatusError):
      status = error.response.status_code
      try:
        code = error.response.json().get("error", {}).get("code")
      except (ValueError, TypeError, AttributeError):
        code = None
    safe_code = code if isinstance(code, str) and code in known_codes else "unknown"
    if safe_code == "model_decommissioned":
      reason = "groq_model_decommissioned"
    elif status == 401:
      reason = "groq_authentication"
    elif status == 403:
      reason = "groq_permission_denied"
    elif status == 404 or safe_code == "model_not_found":
      reason = "groq_model_not_found"
    elif status == 429:
      reason = "groq_rate_limited"
    elif status in (400, 413, 422):
      reason = "groq_invalid_request"
    elif isinstance(error, httpx.TimeoutException):
      reason = "groq_timeout"
    elif isinstance(error, httpx.RequestError):
      reason = "groq_connection_error"
    else:
      reason = "groq_service_unavailable"
    log_event("llm_error", provider="groq", status=status, code=safe_code, reason=reason)
    return ModelUnavailable(reason)

  @staticmethod
  def _record_usage(body):
    usage = body.get("usage") or (body.get("x_groq") or {}).get("usage")
    if not isinstance(usage, dict):
      return
    counts = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
      value = usage.get(name)
      if type(value) is int and 0 <= value <= 10_000_000:
        counts[name] = value
    if counts:
      log_event("llm_usage", provider="groq", **counts)

  def generate(self, question: str, contexts: list) -> GroundedAnswer:
    if not self.slot.acquire(blocking=False):
      raise ModelBusy()
    try:
      response = self.http.post("chat/completions", json=self._payload(question, contexts))
      response.raise_for_status()
      if len(response.content) > 32_000:
        raise InvalidGeneration()
      body = response.json()
      self._record_usage(body)
      choice = body["choices"][0]
      if choice.get("finish_reason") != "stop":
        raise InvalidGeneration()
      return GroundedAnswer.model_validate_json(choice["message"]["content"])
    except httpx.HTTPError as error:
      raise self._failure(error) from error
    except (ValueError, TypeError, KeyError, AttributeError, IndexError) as error:
      raise InvalidGeneration() from error
    finally:
      self.slot.release()

  def stream_generate(self, question: str, contexts: list):
    if not self.slot.acquire(blocking=False):
      raise ModelBusy()
    decoder = IncrementalAnswer()
    deadline = time.monotonic() + self.settings.timeout_seconds
    finished = False
    usage = None
    try:
      with self.http.stream(
        "POST", "chat/completions", json=self._payload(question, contexts, stream=True)
      ) as response:
        if response.status_code >= 300:
          response.read()
        response.raise_for_status()
        for line in response.iter_lines():
          if time.monotonic() > deadline:
            raise self._failure(httpx.ReadTimeout("Generation deadline exceeded"))
          if not line.startswith("data:"):
            continue
          if len(line) > 32_000:
            raise InvalidGeneration()
          data = line[5:].strip()
          if data == "[DONE]":
            if usage:
              self._record_usage(usage)
            if not finished:
              raise InvalidGeneration()
            result = GroundedAnswer.model_validate_json(decoder.content)
            if result.answer != decoder.emitted:
              raise InvalidGeneration()
            yield GenerationChunk(result=result)
            return
          body = json.loads(data)
          if body.get("error"):
            info = body["error"]
            raise self._failure(code=info.get("code") if isinstance(info, dict) else None)
          if body.get("usage") or (body.get("x_groq") or {}).get("usage"):
            usage = body
          choices = body.get("choices", [])
          if not choices:
            continue
          choice = choices[0]
          delta = decoder.feed(choice.get("delta", {}).get("content") or "")
          if delta:
            yield GenerationChunk(delta=delta)
          reason = choice.get("finish_reason")
          if reason is not None:
            if reason != "stop":
              raise InvalidGeneration()
            finished = True
        raise InvalidGeneration()
    except httpx.HTTPError as error:
      raise self._failure(error) from error
    except (ValueError, TypeError, KeyError, AttributeError, IndexError) as error:
      raise InvalidGeneration() from error
    finally:
      self.slot.release()
