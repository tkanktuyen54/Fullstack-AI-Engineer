"""Bounded operational metrics and structured logs; never log prompts or tokens."""

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

request_id = ContextVar("advisor_request_id", default="-")
logger = logging.getLogger("advisor.events")


class JsonFormatter(logging.Formatter):
  def format(self, record):
    return json.dumps(
      {
        "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
        "level": record.levelname,
        "event": record.getMessage(),
        "requestId": request_id.get(),
        **getattr(record, "fields", {}),
      },
      ensure_ascii=False,
    )


def configure_logging():
  if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
  logger.setLevel(logging.INFO)
  logger.propagate = False


def log_event(event, **fields):
  logger.info(event, extra={"fields": fields})


class Telemetry:
  """One registry per app/process. No request/user IDs in metric labels."""

  def __init__(self):
    self.registry = CollectorRegistry()
    self.http = Counter(
      "advisor_http_requests",
      "Completed HTTP requests",
      ["route", "status"],
      registry=self.registry,
    )
    self.duration = Histogram(
      "advisor_http_duration_seconds",
      "HTTP duration including the entire streamed body",
      ["route"],
      buckets=(0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
      registry=self.registry,
    )
    self.active = Gauge("advisor_active_requests", "Active advice requests", registry=self.registry)
    self.retrieval = Histogram(
      "advisor_retrieval_seconds", "Document retrieval duration", registry=self.registry
    )
    self.first_answer = Histogram(
      "advisor_first_answer_seconds",
      "Time to first published answer text, excluding status events",
      buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
      registry=self.registry,
    )
    self.answers = Counter(
      "advisor_answers", "Final SecOps answers", ["mode", "reason"], registry=self.registry
    )
    self.stream_errors = Counter(
      "advisor_stream_errors", "Errors after streaming headers", registry=self.registry
    )

  def record_reply(self, reply):
    self.answers.labels(reply.answerMode, reply.fallbackReason or "none").inc()

  def render(self):
    return generate_latest(self.registry)
