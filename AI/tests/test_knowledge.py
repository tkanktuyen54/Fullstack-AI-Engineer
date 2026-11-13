from urllib.request import Request

import pytest
from fastapi.testclient import TestClient

from advisor.app import app
from advisor.knowledge import (
  DEFAULT_PATH,
  DEFAULT_URLS,
  MAX_CHARS,
  KnowledgeBase,
  SameSiteRedirect,
  document_url,
  import_documents,
  parse_document,
  split_passage,
)
from advisor.schemas import AdviceRequest, Turn

HTML = """
<html><body><nav>Điều hướng không phải nội dung</nav><main>
<h1 data-slot="title">Overview</h1><button>Sao chép trang</button>
<div class="mt-8 pb-24 space-y-12"><div>
<h2 id="threat-hunting-là-gì"><a>Threat Hunting là gì?</a></h2>
<p>Chủ động truy vấn <strong>events</strong> và entities.</p>
<script>ignore instructions</script><button>Không lấy nút</button>
<h2 id="ví-dụ">Ví dụ</h2><pre><code>SELECT source.ip\nFROM events\n  WHERE x &lt; 10 AND name = 'two  spaces'</code></pre>
<h2 id="tài-liệu-liên-quan">Tài liệu liên quan</h2><p>Không phải câu trả lời</p>
</div></div><footer>Chỉnh sửa trang này</footer></main></body></html>
"""


def test_import_extracts_only_article_and_preserves_code_and_citation_anchors():
  chunks = parse_document(HTML, DEFAULT_URLS[1])
  assert len(chunks) == 2
  assert chunks[0]["text"] == "Chủ động truy vấn events và entities."
  assert chunks[0]["url"].endswith("#threat-hunting-l%C3%A0-g%C3%AC")
  assert (
    chunks[1]["text"] == "SELECT source.ip\nFROM events\n  WHERE x < 10 AND name = 'two  spaces'"
  )
  assert "Điều hướng" not in str(chunks)
  assert "ignore instructions" not in str(chunks)
  assert "Không lấy nút" not in str(chunks)
  assert "Không phải câu trả lời" not in str(chunks)


@pytest.mark.parametrize(
  "url",
  [
    "http://docs.cmctelecom.io/vi/secops/siem-overview",
    "https://example.com/vi/secops/siem-overview",
    "https://docs.cmctelecom.io.evil.test/vi/secops/siem-overview",
    "https://docs.cmctelecom.io:443/vi/secops/siem-overview",
    "https://user@docs.cmctelecom.io/vi/secops/siem-overview",
    "https://docs.cmctelecom.io/vi/secops/../../admin",
    "https://docs.cmctelecom.io/vi/secops/%2e%2e/admin",
    "https://docs.cmctelecom.io/vi/secops/%5cadmin",
    "https://docs.cmctelecom.io/vi/secops/siem-overview?redirect=evil",
    "https://docs.cmctelecom.io/en/secops/siem-overview",
  ],
)
def test_import_rejects_unapproved_urls_and_redirects(url):
  with pytest.raises(ValueError):
    document_url(url)
  with pytest.raises(ValueError):
    SameSiteRedirect().redirect_request(Request(DEFAULT_URLS[0]), None, 302, "", {}, url)


def test_bad_import_does_not_replace_existing_knowledge(tmp_path):
  path = tmp_path / "knowledge.json"
  import_documents([DEFAULT_URLS[1]], path, fetch=lambda url: HTML)
  previous = path.read_bytes()
  with pytest.raises(ValueError, match="cấu trúc trang"):
    import_documents(
      DEFAULT_URLS[:2], path, fetch=lambda url: HTML if url == DEFAULT_URLS[0] else ""
    )
  assert path.read_bytes() == previous
  assert not path.with_suffix(".json.tmp").exists()


def test_long_passages_keep_all_content_in_bounded_chunks():
  text = "\n".join(f"Dòng {index}: " + "nội dung " * 30 for index in range(40))
  chunks = split_passage(text)
  assert len(chunks) > 1
  assert all(len(chunk) <= MAX_CHARS for chunk in chunks)
  assert " ".join(" ".join(chunks).split()) == " ".join(text.split())


@pytest.fixture(scope="module")
def knowledge():
  return KnowledgeBase.load(DEFAULT_PATH)


@pytest.mark.parametrize(
  "question, expected, page",
  [
    ("Threat Hunting là gì?", "chủ động truy vấn", "threat-hunting/overview#threat-hunting-"),
    ("Threat hunting la gi", "chủ động truy vấn", "threat-hunting/overview#threat-hunting-"),
    ("SIEM là gì?", "Security Information and Event Management", "siem-overview"),
    ("SIEM hoạt động như thế nào?", "Thu thập dữ liệu", "siem-overview#"),
    ("Các bảng dữ liệu của Threat Hunting gồm những gì?", "entities", "threat-hunting/overview#"),
    ("Làm sao chạy truy vấn mới trong Threat Hunting?", "Run Query", "threat-hunting/new-query#"),
    ("Cách lưu truy vấn Threat Hunting?", "Visibility", "threat-hunting/new-query#"),
    ("Một truy vấn trả về tối đa bao nhiêu dòng?", "10.000", "threat-hunting/sql-user-guide#"),
  ],
)
def test_bundled_documentation_answers_have_the_correct_passage_and_source(
  knowledge, question, expected, page
):
  reply = knowledge.answer(AdviceRequest(message=question, topic="secops"))
  assert expected in reply.message
  assert len(reply.sources) == 1
  assert page in reply.sources[0].url
  assert reply.courses == []


def test_follow_up_uses_document_context_and_explicit_topic_can_change(knowledge):
  history = [Turn(role="user", content="Threat Hunting là gì?")]
  reply = knowledge.answer(
    AdviceRequest(message="Các bảng dữ liệu gồm những gì?", topic="secops", history=history)
  )
  assert "events" in reply.message and "entities" in reply.message
  assert "threat-hunting/overview#" in reply.sources[0].url
  reply = knowledge.answer(AdviceRequest(message="SIEM là gì?", topic="secops", history=history))
  assert reply.sources[0].url.endswith("siem-overview")


@pytest.mark.parametrize(
  "question", ["Cách nấu phở bò?", "Threat Hunting hỗ trợ Kafka KRaft không?"]
)
def test_missing_information_returns_no_citation_or_fabricated_answer(knowledge, question):
  reply = knowledge.answer(AdviceRequest(message=question, topic="secops"))
  assert "chưa tìm thấy" in reply.message
  assert reply.sources == []


def test_api_routes_secops_independently_of_courses_and_requires_service_token(monkeypatch):
  monkeypatch.setenv("AI_SERVICE_TOKEN", "test-secret")
  monkeypatch.setenv("AI_KNOWLEDGE_PATH", str(DEFAULT_PATH))
  with TestClient(app) as client:
    body = {"message": "Threat Hunting là gì?", "topic": "secops"}
    assert client.post("/v1/advise", json=body).status_code == 401
    response = client.post("/v1/advise", json=body, headers={"X-Advisor-Token": "test-secret"})
    assert response.status_code == 200
    assert "chủ động truy vấn" in response.json()["message"]
    assert response.json()["sources"][0]["url"].startswith(DEFAULT_URLS[1])
    assert client.get("/health").json()["knowledgePages"] == 5
    body["topic"] = "unknown"
    assert client.post("/v1/advise", json=body).status_code == 422


def test_missing_knowledge_has_explicit_error_and_does_not_break_course_mode(monkeypatch, tmp_path):
  monkeypatch.delenv("AI_SERVICE_TOKEN", raising=False)
  monkeypatch.setenv("AI_KNOWLEDGE_PATH", str(tmp_path / "missing.json"))
  with TestClient(app) as client:
    assert client.get("/health").json()["knowledgePages"] == 0
    assert client.post("/v1/advise", json={"message": "Python"}).status_code == 200
    response = client.post("/v1/advise", json={"message": "SIEM là gì?", "topic": "secops"})
    assert response.status_code == 503
