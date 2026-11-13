"""Observe full ASGI responses, including stream completion and disconnection."""

import re
import time
import uuid

from starlette.responses import JSONResponse

from ..core.telemetry import log_event, request_id

ROUTES = {"/health", "/health/live", "/health/ready", "/metrics", "/v1/advise", "/v1/advise/stream"}
ADVICE_ROUTES = {"/v1/advise", "/v1/advise/stream"}


class OperationalMiddleware:
  def __init__(self, app):
    self.app = app

  async def __call__(self, scope, receive, send):
    if scope["type"] != "http":
      return await self.app(scope, receive, send)
    headers = dict(scope.get("headers", []))
    candidate = headers.get(b"x-request-id", b"").decode("ascii", errors="ignore")
    identifier = candidate if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", candidate) else uuid.uuid4().hex
    context = request_id.set(identifier)
    state = scope["app"].state
    metrics = state.telemetry
    route = scope["path"] if scope["path"] in ROUTES else "other"
    started = time.monotonic()
    status = 500
    response_started = False
    complete = False
    acquired = False

    async def observed_send(message):
      nonlocal status, complete, response_started
      if message["type"] == "http.response.start":
        response_started = True
        status = message["status"]
        message["headers"] = list(message.get("headers", [])) + [
          (b"x-request-id", identifier.encode("ascii"))
        ]
      await send(message)
      if message["type"] == "http.response.body" and not message.get("more_body", False):
        complete = True

    try:
      if route in ADVICE_ROUTES:
        acquired = state.admission.acquire(blocking=False)
        if not acquired:
          response = JSONResponse(
            {"detail": "AI service is busy"}, status_code=429, headers={"Retry-After": "1"}
          )
          return await response(scope, receive, observed_send)
        metrics.active.inc()
      await self.app(scope, receive, observed_send)
    except Exception as error:
      log_event("http_error", route=route, errorType=type(error).__name__)
      if response_started:
        raise
      response = JSONResponse({"detail": "AI service error"}, status_code=500)
      await response(scope, receive, observed_send)
    finally:
      if acquired:
        state.admission.release()
        metrics.active.dec()
      elapsed = time.monotonic() - started
      outcome = str(status) if complete else "incomplete"
      metrics.http.labels(route, outcome).inc()
      metrics.duration.labels(route).observe(elapsed)
      # Probe and scrape traffic stays out of application event logs.
      if route not in ("/health", "/health/live", "/health/ready", "/metrics"):
        log_event(
          "http_request", route=route, status=status, complete=complete, seconds=round(elapsed, 4)
        )
      request_id.reset(context)
