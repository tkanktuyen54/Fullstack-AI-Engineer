"""ASGI entry point: uvicorn advisor.app:app."""

from fastapi import FastAPI

from .api.middleware import OperationalMiddleware
from .api.routes import router
from .core.runtime import lifespan
from .core.telemetry import Telemetry


def create_app() -> FastAPI:
  application = FastAPI(title="Khoa AI assistant", lifespan=lifespan)
  application.state.telemetry = Telemetry()
  application.add_middleware(OperationalMiddleware)
  application.include_router(router)
  return application


app = create_app()
