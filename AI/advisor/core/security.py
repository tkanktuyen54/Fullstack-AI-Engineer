"""Authentication and basic request validation shared by JSON and streaming routes."""

import hmac
import os

from fastapi import HTTPException

from ..api.schemas import AdviceRequest


def validate_request(request: AdviceRequest, token_header):
  token = os.getenv("AI_SERVICE_TOKEN", "")
  if token and not hmac.compare_digest(token, token_header or ""):
    raise HTTPException(status_code=401, detail="Invalid service token")
  if not request.message.strip():
    raise HTTPException(status_code=422, detail="Message must not be blank")
