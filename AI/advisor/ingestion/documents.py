"""Import and parse public CMC documentation without starting the API or model."""

import argparse
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..core.config import DEFAULT_KNOWLEDGE_PATH

ORIGIN = "https://docs.cmctelecom.io"
PREFIX = "/vi/secops/"
DEFAULT_PATH = DEFAULT_KNOWLEDGE_PATH
DEFAULT_URLS = [
  ORIGIN + PREFIX + path
  for path in (
    "siem-overview",
    "threat-hunting/overview",
    "threat-hunting/new-query",
    "threat-hunting/saved-queries",
    "threat-hunting/sql-user-guide",
    "search/overview",
  )
]
MAX_BYTES = 4_000_000
MAX_CHARS = 2200
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
    self.container_depth = None
    self.article_read = False
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
      self.container_depth = depth
    elif (
      tag == "div"
      and self.container_depth is not None
      and depth == self.container_depth + 1
      and not self.article_read
    ):
      # The first child is the article; sibling blocks contain edit links and page navigation.
      self.body_depth = depth
      self.article_read = True
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
  elif "/search/" in url:
    title = "Search · " + title
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


def main():
  parser = argparse.ArgumentParser(description="Nhập tài liệu CMC SecOps cho trợ lý hỏi đáp.")
  parser.add_argument(
    "urls", nargs="*", help="URL tài liệu; mặc định nhập SIEM, Threat Hunting và Search."
  )
  parser.add_argument("--output", type=Path, default=DEFAULT_PATH)
  args = parser.parse_args()
  try:
    payload = import_documents(args.urls or DEFAULT_URLS, args.output)
  except (OSError, ValueError) as error:
    parser.exit(1, f"Không thể nhập tài liệu: {error}\n")
  print(f"Đã nhập {len(payload['pages'])} trang, {len(payload['chunks'])} đoạn vào {args.output}")


if __name__ == "__main__":
  main()
