# Kiến trúc dịch vụ AI

## Cấu trúc hiện tại

```text
AI/
  advisor/
    app.py                     # Tạo FastAPI app, ghép router và lifespan
    api/
      routes.py                # /health, /v1/advise, /v1/advise/stream
      schemas.py               # Hợp đồng request/response Pydantic
    core/
      config.py                # Biến môi trường, giới hạn model, đường dẫn dữ liệu
      runtime.py               # Nạp tài nguyên lúc khởi động và đóng HTTP client
      security.py              # Token nội bộ, kiểm tra request chung
      text.py                  # Chuẩn hóa tiếng Việt dùng chung
    ingestion/
      catalog.py               # CLI nhập Excel/CSV thành danh mục JSON
      documents.py             # CLI tải, làm sạch, chia đoạn tài liệu CMC
    retrieval/
      knowledge.py             # BM25, ngữ cảnh truy vấn, đáp án trích đoạn
    llm/
      ollama.py                # HTTP client Qwen, giới hạn đồng thời và timeout
      streaming.py             # Giải mã answer từ JSON đang được model sinh
    services/
      courses.py               # Tư vấn khóa học và quy tắc nghiệp vụ
      rag.py                   # Điều phối retrieval → LLM → guardrail/fallback
      guardrails.py            # Kiểm tra đầu vào, prefix, bằng chứng và đầu ra
    training/
      model.py                 # TinyGPT nghiên cứu, tokenizer, checkpoint
      train.py                 # CLI huấn luyện text/chat/intents
      generate.py              # CLI sinh thử bằng TinyGPT
  data/                        # Tài liệu đã nhập và tập dữ liệu mẫu
  artifacts/                   # Checkpoint TinyGPT, không đưa vào Git
  tests/                       # API, nhập dữ liệu, retrieval, model và streaming
  docs/                        # Tài liệu kiến trúc
  .env.example                 # Mẫu biến môi trường, không tự nạp
  pyproject.toml               # Cấu hình Ruff và pytest
  requirements.txt             # Dependency chạy dịch vụ
  requirements-dev.txt         # Dependency kiểm thử/định dạng
  Dockerfile
  README.md
```

Chỉ tạo các package đang có mã sử dụng. `data/` không nằm trong package Python; trọng số Qwen do Ollama lưu bên ngoài project. Đường dẫn mặc định tính từ `core/config.py` về thư mục `AI`, vì vậy việc tách module không làm đổi vị trí kho tài liệu. Các biến `AI_CATALOG_PATH`, `AI_KNOWLEDGE_PATH`, `AI_MODEL_PATH` vẫn cho phép thay đường dẫn triển khai.

## Ranh giới trách nhiệm

- `api` nhận/kiểm tra HTTP và định dạng phản hồi; không chứa thuật toán BM25 hay prompt model.
- `services` điều phối nghiệp vụ; dùng kết quả truy xuất và client LLM, quyết định đáp án cuối hoặc dự phòng.
- `retrieval` tìm đoạn liên quan; không gọi Ollama và không tự tải website khi chat.
- `ingestion` là bước chuẩn bị dữ liệu ngoài lượt chat; thay kho JSON theo cách nguyên tử.
- `llm` đóng gói giao thức Ollama và giải mã stream; không quyết định quyền học, nguồn trích dẫn hay cập nhật database.
- `core/runtime.py` tạo tài nguyên dùng chung một lần trong lifespan; `app.py` giữ ngắn và dễ đọc.
- `training` chứa luồng TinyGPT nghiên cứu; không tải hay huấn luyện lại Qwen trong lúc phục vụ request.

## Luồng hỏi đáp và streaming

```text
FE fetch POST + cookie/CSRF
  → Java /api/chat/messages, lấy lịch sử đúng phiên/chủ đề
  → Python api/routes.py /v1/advise/stream
  → services/rag.py
      → guardrail đầu vào
      → retrieval/knowledge.py lấy đoạn liên quan
      → llm/ollama.py gọi Qwen3 0.6B với stream=true, think=false
      → llm/streaming.py lấy riêng text trong trường answer
      → guardrail kiểm tra prefix trước mỗi nhóm từ
  → JSON lines: status / delta / result
  → Java đọc từng dòng, gửi SSE answer_delta ngay
  → FE nối text vào bản nháp
  → kiểm tra bằng chứng/đáp án cuối
  → Java gửi answer thay thế bản nháp, sources, done
```

Kiểm tra prefix chỉ là kiểm tra sớm theo quy tắc; không chứng minh tính đúng nghĩa của cả đáp án. Bản nháp có thể được thay thế khi kiểm tra cuối thất bại. Chỉ đáp án cuối được ghi vào lịch sử. Nếu kết nối bị ngắt trước `result`, Java không ghi lịch sử và FE xóa bản nháp. Stream không phát nội dung thinking hay trường evidence. API JSON `/v1/advise` vẫn dùng cho client không cần streaming.

## Lệnh sau khi chuyển thư mục

Chạy từ thư mục `AI`, trong virtualenv:

```powershell
python -m uvicorn advisor.app:app --host 127.0.0.1 --port 8000
python -m advisor.ingestion.documents
python -m advisor.ingestion.catalog data/courses.example.csv
python -m advisor.training.train --help
python -m advisor.training.generate --help
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

Điểm chạy ASGI và các API không đổi tên. Các CLI và import Python dùng đường dẫn package mới; lệnh cũ `advisor.catalog`, `advisor.knowledge`, `advisor.train`, `advisor.generate` được thay bằng các lệnh ở trên. Docker tiếp tục copy toàn bộ `advisor/` và chạy `advisor.app:app`.

## Nguồn tham khảo

- [FastAPI — Bigger Applications](https://fastapi.tiangolo.com/tutorial/bigger-applications/): tách API bằng `APIRouter` và ghép ở entry point.
- [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template/tree/master/backend): tham khảo cách tách `api`, `core`, schema và tests trong một backend Python.
- [Microsoft — RAG chat app](https://github.com/Azure-Samples/azure-search-openai-demo): tham khảo ranh giới giữa HTTP, các luồng retrieval/chat và chuẩn bị dữ liệu. Mẫu dùng Azure/Quart; project này giữ FastAPI và Ollama local.
- [Cookiecutter Data Science](https://cookiecutter-data-science.drivendata.org/using-the-template/): phân biệt dữ liệu, mã Python tái sử dụng và hoạt động huấn luyện.
- [Ollama streaming](https://docs.ollama.com/api/streaming): giao thức JSON lines từ model.

Cấu trúc được điều chỉnh theo quy mô project hiện tại; không đưa thêm ORM, cloud SDK hay vector database chỉ để giống các mẫu tham khảo.
