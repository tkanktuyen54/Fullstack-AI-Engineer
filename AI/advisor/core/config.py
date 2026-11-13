"""Environment configuration and workspace paths; importing performs no I/O."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

AI_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KNOWLEDGE_PATH = AI_ROOT / "data" / "secops.json"
DEFAULT_CATALOG_PATH = AI_ROOT / "data" / "catalog.json"


def env_bool(name: str, default: bool) -> bool:
  value = os.getenv(name, str(default)).lower()
  if value not in ("true", "false"):
    raise ValueError(f"{name} phải là true hoặc false.")
  return value == "true"


@dataclass(frozen=True)
class AppSettings:
  environment: str = "development"
  service_token: str = field(default="", repr=False)
  require_knowledge: bool = False
  readiness_require_llm: bool = False
  stream_validation: str = "incremental"
  max_active_requests: int = 8

  @classmethod
  def from_env(cls):
    environment = os.getenv("AI_ENVIRONMENT", "development")
    if environment not in ("development", "test", "production"):
      raise ValueError("AI_ENVIRONMENT phải là development, test hoặc production.")
    settings = cls(
      environment=environment,
      service_token=os.getenv("AI_SERVICE_TOKEN", ""),
      require_knowledge=env_bool("AI_REQUIRE_KNOWLEDGE", False),
      readiness_require_llm=env_bool("AI_READINESS_REQUIRE_LLM", False),
      stream_validation=os.getenv(
        "AI_STREAM_VALIDATION", "complete" if environment == "production" else "incremental"
      ),
      max_active_requests=int(os.getenv("AI_MAX_ACTIVE_REQUESTS", "8")),
    )
    if environment == "production" and (
      len(settings.service_token) < 32 or settings.service_token.isspace()
    ):
      raise ValueError("Production cần AI_SERVICE_TOKEN ít nhất 32 ký tự.")
    if settings.stream_validation not in ("incremental", "complete"):
      raise ValueError("AI_STREAM_VALIDATION phải là incremental hoặc complete.")
    if not 1 <= settings.max_active_requests <= 128:
      raise ValueError("AI_MAX_ACTIVE_REQUESTS phải nằm trong khoảng 1–128.")
    return settings


@dataclass(frozen=True)
class LlmSettings:
  enabled: bool = True
  base_url: str = "http://127.0.0.1:11434"
  model: str = "qwen3:0.6b"
  thinking: bool = False
  context_tokens: int = 2048
  max_output_tokens: int = 256
  timeout_seconds: float = 45
  keep_alive: str = "1m"

  @classmethod
  def from_env(cls):
    settings = cls(
      enabled=env_bool("AI_LLM_ENABLED", True),
      base_url=os.getenv("AI_OLLAMA_URL", cls.base_url).rstrip("/"),
      model=os.getenv("AI_LLM_MODEL", cls.model),
      thinking=env_bool("AI_LLM_THINKING", False),
      context_tokens=int(os.getenv("AI_LLM_CONTEXT_TOKENS", "2048")),
      max_output_tokens=int(os.getenv("AI_LLM_MAX_OUTPUT_TOKENS", "256")),
      timeout_seconds=float(os.getenv("AI_LLM_TIMEOUT_SECONDS", "45")),
      keep_alive=os.getenv("AI_LLM_KEEP_ALIVE", "1m"),
    )
    url = urlsplit(settings.base_url)
    if (
      url.scheme not in ("http", "https")
      or url.hostname not in ("localhost", "127.0.0.1", "::1", "host.docker.internal", "ollama")
      or url.username is not None
      or url.password is not None
      or url.path not in ("", "/")
      or url.query
      or url.fragment
    ):
      raise ValueError("AI_OLLAMA_URL phải là địa chỉ Ollama local hoặc host Docker.")
    if not 1024 <= settings.context_tokens <= 8192:
      raise ValueError("AI_LLM_CONTEXT_TOKENS phải nằm trong khoảng 1024–8192.")
    if not 64 <= settings.max_output_tokens <= 1024:
      raise ValueError("AI_LLM_MAX_OUTPUT_TOKENS phải nằm trong khoảng 64–1024.")
    if not 1 <= settings.timeout_seconds <= 120:
      raise ValueError("AI_LLM_TIMEOUT_SECONDS phải nằm trong khoảng 1–120.")
    if not settings.model.strip() or settings.model.endswith("-cloud"):
      raise ValueError("AI_LLM_MODEL phải là model local.")
    return settings
