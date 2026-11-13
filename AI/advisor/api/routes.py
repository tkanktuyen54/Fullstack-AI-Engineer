"""HTTP transport only; retrieval and generation live in services."""

import json
from contextlib import closing
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.responses import JSONResponse, Response

from ..core.security import validate_request, validate_token
from ..core.telemetry import log_event
from ..llm.selection import selected_llm
from ..services.course_generation import synthesize_courses
from ..services.courses import advise
from ..services.rag import RagService
from .schemas import AdviceReply, AdviceRequest

router = APIRouter()


def runtime(request: AdviceRequest, http: Request, token):
  state = http.app.state
  validate_request(request, token, state.settings.service_token)
  if request.topic == "secops" and state.knowledge is None:
    raise HTTPException(status_code=503, detail="Kho tài liệu CMC SecOps chưa được nhập.")
  return state


@router.get("/health")
def health(http: Request):
  state = http.app.state
  return {
    "status": "ok",
    "modelLoaded": state.model is not None,
    "importedCourses": len(state.catalog),
    "knowledgePages": len(state.knowledge.pages) if state.knowledge else 0,
    "knowledgeChunks": len(state.knowledge.chunks) if state.knowledge else 0,
    "knowledgeUpdatedAt": state.knowledge.updated_at if state.knowledge else None,
    "knowledgeRevision": state.knowledge.revision if state.knowledge else None,
    "llm": state.llm.health(),
  }


@router.get("/health/live")
def live():
  # Liveness must not restart the API just because Ollama is temporarily unavailable.
  return {"status": "alive"}


@router.get("/health/ready")
def ready(http: Request):
  state = http.app.state
  knowledge_ready = bool(state.knowledge and state.knowledge.chunks)
  llm = state.llm.health()
  llm_ready = llm["enabled"] and llm["reachable"] and llm["available"]
  available = (not state.settings.require_knowledge or knowledge_ready) and (
    not state.settings.readiness_require_llm or llm_ready
  )
  status = "ready"
  if llm["enabled"] and not llm_ready:
    status = "degraded"
  if not available:
    status = "not_ready"
  return JSONResponse(
    {
      "status": status,
      "checks": {"knowledge": knowledge_ready, "llm": llm_ready},
      "requirements": {
        "knowledge": state.settings.require_knowledge,
        "llm": state.settings.readiness_require_llm,
      },
    },
    status_code=200 if available else 503,
  )


@router.get("/metrics", include_in_schema=False)
def metrics(http: Request, x_advisor_token: Optional[str] = Header(default=None)):
  validate_token(x_advisor_token, http.app.state.settings.service_token)
  return Response(
    http.app.state.telemetry.render(),
    headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"},
  )


@router.post("/v1/advise", response_model=AdviceReply)
def advice(
  request: AdviceRequest, http: Request, x_advisor_token: Optional[str] = Header(default=None)
):
  state = runtime(request, http, x_advisor_token)
  with selected_llm(state, request) as llm:
    if request.topic == "secops":
      return rag(state, llm).answer(request)
    reply = advise(request, state.catalog, state.model)
    return synthesize_courses(request, reply, llm) if request.llm else reply


def rag(state, llm):
  if llm is state.llm:
    return state.rag
  return RagService(state.knowledge, llm, state.telemetry, state.settings.stream_validation)


@router.post("/v1/advise/stream")
def advice_stream(
  request: AdviceRequest, http: Request, x_advisor_token: Optional[str] = Header(default=None)
):
  state = runtime(request, http, x_advisor_token)

  def events():
    with selected_llm(state, request) as llm:
      if request.topic == "secops":
        yield from rag(state, llm).stream(request)
      else:
        reply = advise(request, state.catalog, state.model)
        if request.llm:
          reply = synthesize_courses(request, reply, llm)
        yield {"type": "result", "reply": reply.model_dump(mode="json")}

  def lines():
    try:
      with closing(events()) as stream:
        for event in stream:
          yield json.dumps(event, ensure_ascii=False) + "\n"
    except Exception as error:
      state.telemetry.stream_errors.inc()
      log_event("stream_error", errorType=type(error).__name__)
      yield (
        json.dumps(
          {"type": "error", "message": "Trợ lý chưa trả lời được. Bạn thử lại nhé."},
          ensure_ascii=False,
        )
        + "\n"
      )

  return StreamingResponse(
    lines(),
    media_type="application/x-ndjson",
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
  )
