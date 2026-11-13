"""Authentication and basic request validation shared by JSON and streaming routes."""

import hmac
import os

from fastapi import HTTPException

from ..api.schemas import AdviceRequest


def validate_token(token_header, expected_token=None):
  token = os.getenv("AI_SERVICE_TOKEN", "") if expected_token is None else expected_token
  if token and not hmac.compare_digest(token.encode(), (token_header or "").encode()):
    raise HTTPException(status_code=401, detail="Invalid service token")


def validate_request(request: AdviceRequest, token_header, expected_token=None):
  validate_token(token_header, expected_token)
  if not request.message.strip():
    raise HTTPException(status_code=422, detail="Message must not be blank")
