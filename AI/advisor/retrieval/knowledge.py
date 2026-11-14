"""BM25 retrieval and extractive answers, independent of the HTTP/model clients."""

import json
import math
import re
from collections import Counter
from hashlib import sha256
from pathlib import Path

from ..api.schemas import AdviceReply, AdviceRequest, DocumentSource
from ..core.config import DEFAULT_KNOWLEDGE_PATH
from ..core.text import normalize
from ..ingestion.documents import document_url

DEFAULT_PATH = DEFAULT_KNOWLEDGE_PATH
STOP_WORDS = set(
  "toi minh ban em anh chi muon can xin hay giup cho biet ve la gi nao the nhu tai sao "
  "duoc khong co nhung cac mot va voi cua trong tren tu den nay do ay thi ma se "
  "lam cach the nao huong dan giai thich them tiep tuc bao nhieu gom nhung "
  "theo tai lieu cmc secops tra loi cau hoi ho tro vui long o dau".split()
)


def terms(text: str) -> list:
  text = normalize(text)
  # Generic feature wrappers must not satisfy coverage when the subject is absent.
  text = re.sub(r"\b(?:tinh nang|chuc nang)\b", " ", text)
  # A result-row limit and a returned-row limit refer to the same execution constraint.
  text = re.sub(r"\bdong ket qua\b", "dong tra ve", text)
  for pattern, expansion in (
    (r"\bnew query\b", "tao chay truy van moi"),
    (r"\b(?:query|queries)\b", "truy van"),
    (r"\brun\b", "chay"),
    (r"\bsave\b", "luu"),
  ):
    if re.search(pattern, text):
      text += " " + expansion
  if "san tim" in text or "san lung" in text:
    text += " threat hunting"
  return [word for word in re.findall(r"[a-z0-9_]+", text) if word not in STOP_WORDS]


def feature_scope(question: str) -> str:
  """Explicit product names override prior conversation context and incidental word matches."""
  question = normalize(question)
  for pattern, path in (
    (r"\b(?:saved queries|truy van da luu)\b", "threat-hunting/saved-queries"),
    (r"\bthreat hunting\b", "threat-hunting/"),
    (r"\bsql user guide\b", "threat-hunting/sql-user-guide"),
  ):
    if re.search(pattern, question):
      return "https://docs.cmctelecom.io/vi/secops/" + path
  # An input labelled Search inside another screen is not the Search product feature.
  if re.search(r"\b(?:search|(?:tinh nang|chuc nang) tim kiem)\b", question) and not re.search(
    r"\bo search\b", question
  ):
    return "https://docs.cmctelecom.io/vi/secops/search/"
  if re.search(r"\bsiem\b", question):
    return "https://docs.cmctelecom.io/vi/secops/siem-overview"
  return ""


class KnowledgeBase:
  def __init__(self, payload: dict):
    if payload.get("version") != 1:
      raise ValueError("Phiên bản kho tài liệu không được hỗ trợ.")
    self.updated_at = payload["fetchedAt"]
    self.pages = payload["pages"]
    self.chunks = payload["chunks"]
    self.revision = sha256(
      json.dumps(self.chunks, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    for page in self.pages:
      document_url(page)
    for chunk in self.chunks:
      document_url(chunk["url"])
      if not all(isinstance(chunk[key], str) for key in ("title", "heading", "text")):
        raise ValueError("Đoạn tài liệu không hợp lệ.")
    self.documents = [
      Counter(terms(chunk["text"] + " " + (chunk["title"] + " " + chunk["heading"] + " ") * 3))
      for chunk in self.chunks
    ]
    frequencies = Counter(word for document in self.documents for word in document)
    self.idf = {
      word: math.log(1 + (len(self.chunks) - count + 0.5) / (count + 0.5))
      for word, count in frequencies.items()
    }
    self.average_length = sum(sum(document.values()) for document in self.documents) / max(
      1, len(self.documents)
    )

  @classmethod
  def load(cls, path: Path):
    return cls(json.loads(path.read_text(encoding="utf-8")))

  def search(self, question: str, page: str = "") -> list:
    normalized = normalize(question)
    scope = feature_scope(question)
    query = set(terms(question))
    if not query:
      return []
    results = []
    for index, (chunk, document) in enumerate(zip(self.chunks, self.documents)):
      page_url = chunk["url"].split("#")[0]
      if page and page_url != page:
        continue
      if scope and (not page_url.startswith(scope) if scope.endswith("/") else page_url != scope):
        continue
      coverage = len(query & document.keys()) / len(query)
      if coverage < 0.65:
        continue
      length = sum(document.values())
      score = sum(
        self.idf.get(word, 0)
        * (document[word] * 2.2)
        / (document[word] + 1.2 * (0.25 + 0.75 * length / self.average_length))
        for word in query
        if document[word]
      )
      heading = set(terms(chunk["heading"]))
      if query <= heading:
        score *= 2
      # Match question forms to section labels, while still requiring content coverage.
      label = normalize(chunk["heading"])
      if "la gi" in normalized and ("la gi" in label or label == "tong quan"):
        score *= 3
      if re.search(r"\b(?:chay|tao|run)\b.*\btruy van\b", normalized):
        if "/new-query#" in chunk["url"] and label == "cac buoc thuc hien":
          score *= 3
      if re.search(r"toi da|gioi han|bao nhieu", normalized):
        if "gioi han" in label and re.search(r"dong|ket qua|thoi gian|chay", normalized):
          score *= 3
      results.append((score * coverage, index))
    return sorted(results, reverse=True)

  def retrieve(self, request: AdviceRequest) -> list:
    page = ""
    # Resolve follow-up questions within the last cited page; explicit topics start a new search.
    previous = [turn.content for turn in request.history if turn.role == "user"]
    if not feature_scope(request.message):
      for question in previous:
        if feature_scope(question):
          page = ""
        prior = self.search(question, page) or self.search(question)
        if prior:
          page = self.chunks[prior[0][1]]["url"].split("#")[0]
    question = normalize(request.message)
    if (
      re.search(r"\b(?:toi da|gioi han)\b", question)
      and re.search(r"\b(?:dong|ket qua|thoi gian|runtime)\b", question)
      and not re.search(r"hien thi|max result shown", question)
    ):
      # Execution limits live in the SQL guide even after a New Query follow-up.
      page = ""
    matches = self.search(request.message, page)
    if not matches and page:
      matches = self.search(request.message)
    if not matches:
      return []
    best = self.chunks[matches[0][1]]
    selected = [
      chunk
      for chunk in self.chunks
      if chunk["url"] == best["url"] and chunk["heading"] == best["heading"]
    ]
    start = selected.index(best)
    return selected[start : start + 3]

  def answer(self, request: AdviceRequest, passages=None) -> AdviceReply:
    selected = self.retrieve(request) if passages is None else passages
    if not selected:
      return AdviceReply(
        message="Mình chưa tìm thấy thông tin đủ phù hợp trong tài liệu CMC SecOps đã nhập. Bạn hãy nêu rõ tính năng hoặc nội dung cần tra cứu.",
        intent="documentation",
        courses=[],
        engine="secops-bm25",
        answerMode="not_found",
      )
    best = selected[0]
    text = "\n\n".join(chunk["text"] for chunk in selected)
    return AdviceReply(
      message=f"Theo tài liệu CMC SecOps — {best['heading']}:\n\n{text}",
      intent="documentation",
      courses=[],
      engine="secops-bm25",
      sources=[DocumentSource(title=best["title"] + " — " + best["heading"], url=best["url"])],
      answerMode="extractive",
    )
