"""Create and close shared runtime resources through FastAPI lifespan."""

import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import torch
from fastapi import FastAPI

from ..ingestion.catalog import load_catalog
from ..llm.ollama import OllamaClient
from ..retrieval.knowledge import KnowledgeBase
from ..services.rag import RagService
from ..training.model import load_model
from .config import DEFAULT_CATALOG_PATH, DEFAULT_KNOWLEDGE_PATH, AppSettings, LlmSettings
from .telemetry import configure_logging, log_event


@asynccontextmanager
async def lifespan(app: FastAPI):
  settings = AppSettings.from_env()
  configure_logging()
  app.state.settings = settings
  app.state.admission = threading.BoundedSemaphore(settings.max_active_requests)
  torch.set_num_threads(int(os.getenv("AI_TORCH_THREADS", "2")))
  path = Path(os.getenv("AI_CATALOG_PATH", str(DEFAULT_CATALOG_PATH)))
  app.state.catalog = load_catalog(path) if path.exists() else []
  knowledge_path = Path(os.getenv("AI_KNOWLEDGE_PATH", str(DEFAULT_KNOWLEDGE_PATH)))
  app.state.knowledge = KnowledgeBase.load(knowledge_path) if knowledge_path.exists() else None
  app.state.model = None
  checkpoint = os.getenv("AI_MODEL_PATH", "")
  if checkpoint:
    app.state.model, metadata = load_model(Path(checkpoint))
    if metadata.get("task") != "intents":
      raise ValueError("AI_MODEL_PATH phải là checkpoint đã huấn luyện task intents.")
  app.state.llm = OllamaClient(LlmSettings.from_env())
  app.state.rag = RagService(
    app.state.knowledge,
    app.state.llm,
    telemetry=app.state.telemetry,
    stream_validation=settings.stream_validation,
  )
  log_event(
    "service_started",
    environment=settings.environment,
    streamValidation=settings.stream_validation,
    maxActiveRequests=settings.max_active_requests,
  )
  try:
    yield
  finally:
    app.state.llm.close()
