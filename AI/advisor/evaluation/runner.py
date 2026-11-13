"""Evaluate public-document questions without paid APIs or an LLM judge.

Fact checks are lexical regression checks, not proof of semantic correctness.
"""

import argparse
import json
import math
import platform
import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..api.schemas import AdviceReply, AdviceRequest, Turn
from ..core.config import AI_ROOT, DEFAULT_KNOWLEDGE_PATH, LlmSettings
from ..core.text import normalize
from ..llm.ollama import OllamaClient
from ..retrieval.knowledge import KnowledgeBase
from ..services.rag import RagService

DEFAULT_DATASET = AI_ROOT / "evals" / "secops.json"


class SourceLabel(BaseModel):
  model_config = ConfigDict(extra="forbid")
  path: str = Field(pattern=r"^/vi/secops/[a-z0-9/-]+$")
  heading: str = Field(min_length=1)


class EvaluationCase(BaseModel):
  model_config = ConfigDict(extra="forbid")
  id: str = Field(pattern=r"^[a-z0-9-]{1,80}$")
  question: str = Field(min_length=1, max_length=2000)
  history: list[Turn] = Field(default_factory=list, max_length=12)
  expectedMode: Literal["answer", "not_found", "blocked"]
  sources: list[SourceLabel] = Field(default_factory=list)
  requiredFacts: list[str] = Field(default_factory=list)
  forbiddenFacts: list[str] = Field(default_factory=list)
  referenceAnswer: str = Field(min_length=1)

  @model_validator(mode="after")
  def labels_match_mode(self):
    if self.expectedMode == "answer" and (not self.sources or not self.requiredFacts):
      raise ValueError("Answerable cases require source labels and required facts.")
    if self.expectedMode != "answer" and (self.sources or self.requiredFacts):
      raise ValueError("Abstention/blocked cases cannot require an answer or source.")
    if any(not fact.strip() for fact in self.requiredFacts + self.forbiddenFacts):
      raise ValueError("Fact labels must not be blank.")
    return self


def load_cases(path):
  payload = json.loads(Path(path).read_text(encoding="utf-8"))
  if payload.get("version") != 1 or not payload.get("cases"):
    raise ValueError("Evaluation dataset must be a nonempty version 1 dataset.")
  cases = [EvaluationCase.model_validate(case) for case in payload["cases"]]
  if len({case.id for case in cases}) != len(cases):
    raise ValueError("Evaluation IDs must be unique.")
  return cases


def source_matches(label, url, heading=None):
  page = url.split("#")[0]
  if page != "https://docs.cmctelecom.io" + label.path:
    return False
  if heading is not None:
    return normalize(heading) == normalize(label.heading)
  # Citation titles have 'page title — heading'; checking them is done by the caller.
  return True


def has_fact(text, fact):
  return bool(re.search(r"(?<!\w)" + re.escape(normalize(fact)) + r"(?!\w)", normalize(text)))


def grade(case, passages, reply):
  answerable = case.expectedMode == "answer"
  checks = {
    "mode": reply.answerMode in ("generated", "extractive")
    if answerable
    else reply.answerMode == case.expectedMode,
    "retrieval": all(
      any(source_matches(label, chunk["url"], chunk["heading"]) for chunk in passages)
      for label in case.sources
    )
    if answerable
    else True,
    "citations": all(
      any(
        source_matches(label, source.url) and source.title.endswith(" — " + label.heading)
        for source in reply.sources
      )
      for label in case.sources
    )
    if answerable
    else not reply.sources,
    "requiredFacts": all(has_fact(reply.message, fact) for fact in case.requiredFacts),
    "forbiddenFacts": not any(has_fact(reply.message, fact) for fact in case.forbiddenFacts),
  }
  return checks


def fraction(items):
  return sum(items) / len(items) if items else None


def evaluate(cases, knowledge, rag):
  results = []
  for case in cases:
    request = AdviceRequest(message=case.question, history=case.history, topic="secops")
    passages = knowledge.retrieve(request) if case.expectedMode == "answer" else []
    started = time.monotonic()
    first_answer = None
    reply = None
    for event in rag.stream(request):
      if event["type"] in ("delta", "result") and first_answer is None:
        first_answer = time.monotonic() - started
      if event["type"] == "result":
        reply = AdviceReply.model_validate(event["reply"])
    if reply is None:
      raise ValueError(f"No final result for evaluation {case.id}.")
    checks = grade(case, passages, reply)
    results.append(
      {
        "id": case.id,
        "expectedMode": case.expectedMode,
        "passed": all(checks.values()),
        "checks": checks,
        "answerMode": reply.answerMode,
        "fallbackReason": reply.fallbackReason,
        "seconds": round(time.monotonic() - started, 4),
        "firstAnswerSeconds": round(first_answer, 4) if first_answer is not None else None,
        "reply": reply.model_dump(mode="json"),
      }
    )
  answerable = [result for result in results if result["expectedMode"] == "answer"]
  durations = sorted(result["seconds"] for result in results)
  return {
    "metrics": {
      "casePassRate": fraction([result["passed"] for result in results]),
      "retrievalHitRate": fraction([result["checks"]["retrieval"] for result in answerable]),
      "generatedRate": fraction([result["answerMode"] == "generated" for result in answerable]),
      "generatedChecksPassRate": fraction(
        [result["passed"] for result in answerable if result["answerMode"] == "generated"]
      ),
      "abstentionAccuracy": fraction(
        [result["passed"] for result in results if result["expectedMode"] == "not_found"]
      ),
      "blockedAccuracy": fraction(
        [result["passed"] for result in results if result["expectedMode"] == "blocked"]
      ),
      "latencyP95Seconds": durations[math.ceil(len(durations) * 0.95) - 1],
    },
    "cases": results,
  }


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--mode", choices=("retrieval", "rag"), default="retrieval")
  parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
  parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE_PATH)
  parser.add_argument("--output", type=Path)
  parser.add_argument("--min-pass-rate", type=float, default=1.0)
  parser.add_argument("--min-generated-rate", type=float, default=0.0)
  parser.add_argument(
    "--stream-validation", choices=("incremental", "complete"), default="incremental"
  )
  args = parser.parse_args()
  for threshold in (args.min_pass_rate, args.min_generated_rate):
    if not 0 <= threshold <= 1:
      parser.error("Thresholds must be between 0 and 1.")
  if args.mode == "retrieval" and args.min_generated_rate:
    parser.error("--min-generated-rate requires --mode rag.")
  try:
    cases = load_cases(args.dataset)
    knowledge = KnowledgeBase.load(args.knowledge)
    settings = LlmSettings.from_env()
    if args.mode == "retrieval":
      settings = replace(settings, enabled=False)
    llm = OllamaClient(settings)
    try:
      report = evaluate(
        cases, knowledge, RagService(knowledge, llm, stream_validation=args.stream_validation)
      )
    finally:
      llm.close()
    report["manifest"] = {
      "evaluatedAt": datetime.now(timezone.utc).isoformat(),
      "mode": args.mode,
      "python": platform.python_version(),
      "model": settings.model if settings.enabled else None,
      "contextTokens": settings.context_tokens,
      "maxOutputTokens": settings.max_output_tokens,
      "thinking": settings.thinking,
      "streamValidation": args.stream_validation,
      "knowledgeRevision": knowledge.revision,
      "knowledgeUpdatedAt": knowledge.updated_at,
      "datasetSha256": sha256(args.dataset.read_bytes()).hexdigest(),
      "limitations": "Lexical facts and source labels are regression checks; human semantic review is required.",
    }
    if args.output:
      args.output.parent.mkdir(parents=True, exist_ok=True)
      args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
      )
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    for result in report["cases"]:
      if not result["passed"]:
        failed = ", ".join(key for key, value in result["checks"].items() if not value)
        print(f"FAIL {result['id']}: {failed}")
    if (
      report["metrics"]["casePassRate"] < args.min_pass_rate
      or (report["metrics"]["generatedRate"] or 0) < args.min_generated_rate
    ):
      parser.exit(1, "Evaluation thresholds were not met.\n")
  except (OSError, ValueError) as error:
    parser.exit(2, f"Cannot evaluate: {error}\n")


if __name__ == "__main__":
  main()
