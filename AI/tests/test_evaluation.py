import json

import httpx
import pytest

from advisor.core.config import LlmSettings
from advisor.evaluation.runner import DEFAULT_DATASET, evaluate, grade, load_cases
from advisor.llm.ollama import OllamaClient
from advisor.retrieval.knowledge import DEFAULT_PATH, KnowledgeBase
from advisor.services.rag import RagService


def test_public_regression_dataset_runs_without_contacting_a_model():
  knowledge = KnowledgeBase.load(DEFAULT_PATH)
  llm = OllamaClient(
    LlmSettings(enabled=False), transport=httpx.MockTransport(lambda request: pytest.fail("HTTP"))
  )
  try:
    report = evaluate(load_cases(DEFAULT_DATASET), knowledge, RagService(knowledge, llm))
    assert len(report["cases"]) >= 15
    assert report["metrics"]["casePassRate"] == 1, [
      result for result in report["cases"] if not result["passed"]
    ]
    assert report["metrics"]["generatedRate"] == 0
    assert report["metrics"]["generatedChecksPassRate"] is None
  finally:
    llm.close()


def test_evaluator_rejects_wrong_heading_missing_fact_and_made_up_number():
  case = load_cases(DEFAULT_DATASET)[8]
  knowledge = KnowledgeBase.load(DEFAULT_PATH)
  from advisor.api.schemas import AdviceRequest

  request = AdviceRequest(message=case.question, topic="secops")
  passages = knowledge.retrieve(request)
  reply = knowledge.answer(request)
  assert all(grade(case, passages, reply).values())
  bad = reply.model_copy(update={"message": "Tối đa 9999 dòng.", "sources": []})
  checks = grade(case, passages, bad)
  assert not checks["requiredFacts"] and not checks["forbiddenFacts"] and not checks["citations"]
  wrong_passage = [{**passages[0], "heading": "Không phải giới hạn thực thi"}]
  assert not grade(case, wrong_passage, reply)["retrieval"]


def test_dataset_rejects_duplicate_ids_and_missing_source_labels(tmp_path):
  payload = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
  payload["cases"] = [payload["cases"][0], payload["cases"][0]]
  path = tmp_path / "bad.json"
  path.write_text(json.dumps(payload), encoding="utf-8")
  with pytest.raises(ValueError, match="unique"):
    load_cases(path)
  payload["cases"] = [payload["cases"][0]]
  payload["cases"][0]["sources"] = []
  path.write_text(json.dumps(payload), encoding="utf-8")
  with pytest.raises(ValueError, match="source labels"):
    load_cases(path)
