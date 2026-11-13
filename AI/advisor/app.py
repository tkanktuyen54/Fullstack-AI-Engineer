"""ASGI entry point: uvicorn advisor.app:app."""

from fastapi import FastAPI

from .api.routes import router
from .core.runtime import lifespan


def create_app() -> FastAPI:
  application = FastAPI(title="Khoa AI assistant", lifespan=lifespan)
  application.include_router(router)
  return application


app = create_app()
