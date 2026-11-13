"""HTTP transport only; retrieval and generation live in services."""

import json
from contextlib import closing
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..core.security import validate_request
from ..services.courses import advise
from .schemas import AdviceReply, AdviceRequest

router = APIRouter()


def runtime(request: AdviceRequest, http: Request, token):
  validate_request(request, token)
  state = http.app.state
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
    "llm": state.llm.health(),
  }


@router.post("/v1/advise", response_model=AdviceReply)
def advice(
  request: AdviceRequest, http: Request, x_advisor_token: Optional[str] = Header(default=None)
):
  state = runtime(request, http, x_advisor_token)
  if request.topic == "secops":
    return state.rag.answer(request)
  return advise(request, state.catalog, state.model)


@router.post("/v1/advise/stream")
def advice_stream(
  request: AdviceRequest, http: Request, x_advisor_token: Optional[str] = Header(default=None)
):
  state = runtime(request, http, x_advisor_token)

  def events():
    if request.topic == "secops":
      yield from state.rag.stream(request)
    else:
      reply = advise(request, state.catalog, state.model)
      yield {"type": "result", "reply": reply.model_dump(mode="json")}

  def lines():
    try:
      with closing(events()) as stream:
        for event in stream:
          yield json.dumps(event, ensure_ascii=False) + "\n"
    except Exception:
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
