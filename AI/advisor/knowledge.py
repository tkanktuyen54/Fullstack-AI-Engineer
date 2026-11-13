"""Import CMC's public documentation and retrieve cited passages without an external LLM."""

import argparse
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .catalog import normalize
from .schemas import AdviceReply, AdviceRequest, DocumentSource

ORIGIN = "https://docs.cmctelecom.io"
PREFIX = "/vi/secops/"
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "secops.json"
DEFAULT_URLS = [
  ORIGIN + PREFIX + path
  for path in (
    "siem-overview",
    "threat-hunting/overview",
    "threat-hunting/new-query",
    "threat-hunting/saved-queries",
    "threat-hunting/sql-user-guide",
  )
]
MAX_BYTES = 4_000_000
MAX_CHARS = 2200
STOP_WORDS = set(
  "toi minh ban em anh chi muon can xin hay giup cho biet ve la gi nao the nhu tai sao "
  "duoc khong co nhung cac mot va voi cua trong tren tu den nay do ay thi ma se "
  "lam cach the nao huong dan giai thich them tiep tuc bao nhieu gom nhung "
  "theo tai lieu cmc secops tra loi cau hoi ho tro vui long o dau".split()
)
VOID_TAGS = {
  "area",
  "base",
  "br",
  "col",
  "embed",
  "hr",
  "img",
  "input",
  "link",
  "meta",
  "source",
  "wbr",
}


def document_url(value: str) -> str:
  parts = urlsplit(value)
  path = unquote(parts.path)
  if (
    parts.scheme != "https"
    or parts.netloc != "docs.cmctelecom.io"
    or not path.startswith(PREFIX)
    or any(part in (".", "..") for part in path.split("/"))
    or "\\" in path
    or parts.query
  ):
    raise ValueError("Chỉ nhận URL HTTPS thuộc https://docs.cmctelecom.io/vi/secops/.")
  return urlunsplit((parts.scheme, parts.netloc, path.rstrip("/"), "", ""))


class SameSiteRedirect(HTTPRedirectHandler):
  def redirect_request(self, request, fp, code, msg, headers, newurl):
    document_url(newurl)
    return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch_document(url: str) -> str:
  request = Request(document_url(url), headers={"User-Agent": "Khoa-Docs-Importer/1.0"})
  with build_opener(SameSiteRedirect()).open(request, timeout=20) as response:
    if response.headers.get_content_type() != "text/html":
      raise ValueError(f"Nguồn không phải trang HTML: {url}")
    data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
      raise ValueError(f"Trang vượt giới hạn {MAX_BYTES} bytes: {url}")
    return data.decode("utf-8")


class DocumentationParser(HTMLParser):
  """Read the Nuxt docs title and article body, excluding navigation and page tools."""

  def __init__(self):
    super().__init__(convert_charrefs=True)
    self.stack = []
    self.title = []
    self.title_depth = None
    self.body_depth = None
    self.skip_depth = None
    self.heading_depth = None
    self.heading_parts = []
    self.heading = "Tổng quan"
    self.anchor = ""
    self.parts = []
    self.pre_depth = None
    self.pre_parts = []
    self.code_blocks = []
    self.sections = []

  def flush(self):
    text = "".join(self.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    for index, code in enumerate(self.code_blocks):
      text = text.replace(f"\x00CODE{index}\x00", code)
    if text and self.heading != "Tài liệu liên quan":
      self.sections.append((self.heading, self.anchor, text))
    self.parts = []
    self.code_blocks = []

  def handle_starttag(self, tag, attrs):
    attrs = dict(attrs)
    if tag not in VOID_TAGS:
      self.stack.append(tag)
    depth = len(self.stack)
    if tag == "h1" and attrs.get("data-slot") == "title":
      self.title_depth = depth
    classes = set(attrs.get("class", "").split())
    if tag == "div" and {"mt-8", "pb-24", "space-y-12"} <= classes:
      self.body_depth = depth
    if self.body_depth is None:
      return
    if tag in ("script", "style", "nav", "button", "svg") and self.skip_depth is None:
      self.skip_depth = depth
    if self.skip_depth is not None:
      return
    if tag == "pre":
      self.pre_depth = depth
      self.pre_parts = []
    if self.pre_depth is not None:
      return
    if tag in ("h2", "h3", "h4", "h5", "h6"):
      self.flush()
      self.heading_parts = []
      self.heading_depth = depth
      self.anchor = attrs.get("id", "")
    elif self.heading_depth is None:
      if tag == "li":
        self.parts.append("\n- ")
      elif tag in ("p", "pre", "tr", "br"):
        self.parts.append("\n")
      elif tag in ("td", "th"):
        self.parts.append(" | ")

  def handle_endtag(self, tag):
    if tag in VOID_TAGS or tag not in self.stack:
      return
    depth = len(self.stack)
    if self.title_depth == depth:
      self.title_depth = None
    if self.heading_depth == depth:
      self.heading = "".join(self.heading_parts).strip()
      self.heading_depth = None
    if self.skip_depth == depth:
      self.skip_depth = None
    elif self.body_depth is not None and self.heading_depth is None:
      if self.pre_depth == depth:
        placeholder = f"\x00CODE{len(self.code_blocks)}\x00"
        self.code_blocks.append("".join(self.pre_parts).strip("\n"))
        self.parts.append("\n" + placeholder + "\n")
        self.pre_depth = None
      if tag in ("p", "li", "pre", "tr", "ul", "ol"):
        self.parts.append("\n")
      if self.body_depth == depth:
        self.flush()
        self.body_depth = None
    del self.stack[len(self.stack) - 1 - self.stack[::-1].index(tag) :]

  def handle_data(self, data):
    if self.title_depth is not None:
      self.title.append(data)
    if self.body_depth is None or self.skip_depth is not None:
      return
    if self.pre_depth is not None:
      self.pre_parts.append(data)
    elif self.heading_depth is not None:
      self.heading_parts.append(data)
    else:
      self.parts.append(data)


def split_passage(text: str) -> list:
  passages = []
  while len(text) > MAX_CHARS:
    end = text.rfind("\n", 0, MAX_CHARS)
    if end < MAX_CHARS // 2:
      end = text.rfind(" ", 0, MAX_CHARS)
    if end <= 0:
      end = MAX_CHARS
    passages.append(text[:end].strip())
    text = text[end:].strip()
  if text:
    passages.append(text)
  return passages


def parse_document(html: str, url: str) -> list:
  url = document_url(url)
  parser = DocumentationParser()
  parser.feed(html)
  parser.close()
  if not parser.sections:
    raise ValueError(f"Không tìm thấy nội dung tài liệu; cần kiểm tra cấu trúc trang: {url}")
  title = "".join(parser.title).strip() or "CMC SecOps"
  if "/threat-hunting/" in url:
    title = "Threat Hunting · " + title
  return [
    {
      "title": title,
      "heading": heading,
      "url": url + ("#" + quote(anchor) if anchor else ""),
      "text": passage,
    }
    for heading, anchor, text in parser.sections
    for passage in split_passage(text)
  ]


def import_documents(urls: list, output: Path, fetch=fetch_document) -> dict:
  urls = list(dict.fromkeys(document_url(url) for url in urls))
  if not urls or len(urls) > 150:
    raise ValueError("Mỗi lần nhập cần từ 1 đến 150 trang.")
  chunks = []
  for url in urls:
    chunks.extend(parse_document(fetch(url), url))
  payload = {
    "version": 1,
    "fetchedAt": datetime.now(timezone.utc).isoformat(),
    "pages": urls,
    "chunks": chunks,
  }
  output.parent.mkdir(parents=True, exist_ok=True)
  temporary = output.with_suffix(output.suffix + ".tmp")
  try:
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
      stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(output)
  finally:
    temporary.unlink(missing_ok=True)
  return payload


def terms(text: str) -> list:
  text = normalize(text)
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


class KnowledgeBase:
  def __init__(self, payload: dict):
    if payload.get("version") != 1:
      raise ValueError("Phiên bản kho tài liệu không được hỗ trợ.")
    self.updated_at = payload["fetchedAt"]
    self.pages = payload["pages"]
    self.chunks = payload["chunks"]
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
    query = set(terms(question))
    if not query:
      return []
    results = []
    for index, (chunk, document) in enumerate(zip(self.chunks, self.documents)):
      if page and chunk["url"].split("#")[0] != page:
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

  def answer(self, request: AdviceRequest) -> AdviceReply:
    page = ""
    # Resolve follow-up questions within the last cited page; explicit topics start a new search.
    previous = [turn.content for turn in request.history if turn.role == "user"]
    if not re.search(r"\b(?:siem|threat hunting)\b", normalize(request.message)):
      for question in previous:
        if re.search(r"\b(?:siem|threat hunting)\b", normalize(question)):
          page = ""
        prior = self.search(question, page) or self.search(question)
        if prior:
          page = self.chunks[prior[0][1]]["url"].split("#")[0]
    matches = self.search(request.message, page)
    if not matches and page:
      matches = self.search(request.message)
    if not matches:
      return AdviceReply(
        message="Mình chưa tìm thấy thông tin đủ phù hợp trong tài liệu CMC SecOps đã nhập. Bạn hãy nêu rõ tính năng hoặc nội dung cần tra cứu.",
        intent="documentation",
        courses=[],
        engine="secops-bm25",
      )
    best = self.chunks[matches[0][1]]
    # Keep adjacent parts of the same section together, in source order.
    selected = [
      chunk
      for chunk in self.chunks
      if chunk["url"] == best["url"] and chunk["heading"] == best["heading"]
    ]
    # Start at the matching part for long sections, rather than returning an unrelated prefix.
    start = selected.index(best)
    selected = selected[start : start + 3]
    text = "\n\n".join(chunk["text"] for chunk in selected)
    return AdviceReply(
      message=f"Theo tài liệu CMC SecOps — {best['heading']}:\n\n{text}",
      intent="documentation",
      courses=[],
      engine="secops-bm25",
      sources=[DocumentSource(title=best["title"] + " — " + best["heading"], url=best["url"])],
    )


def main():
  parser = argparse.ArgumentParser(description="Nhập tài liệu CMC SecOps cho trợ lý hỏi đáp.")
  parser.add_argument("urls", nargs="*", help="URL tài liệu; mặc định nhập SIEM và Threat Hunting.")
  parser.add_argument("--output", type=Path, default=DEFAULT_PATH)
  args = parser.parse_args()
  try:
    payload = import_documents(args.urls or DEFAULT_URLS, args.output)
  except (OSError, ValueError) as error:
    parser.exit(1, f"Không thể nhập tài liệu: {error}\n")
  print(f"Đã nhập {len(payload['pages'])} trang, {len(payload['chunks'])} đoạn vào {args.output}")


if __name__ == "__main__":
  main()
