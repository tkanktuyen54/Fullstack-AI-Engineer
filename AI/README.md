# Trợ lý AI — khóa học và tài liệu CMC SecOps

Angular mở sidebar bên phải → Spring Boot giữ phiên, CSRF và dữ liệu website → Python tư vấn → SSE trả kết quả và thẻ khóa học.

## Chọn model local hoặc Groq

Mở **Cấu hình model** (`/model-config`) từ thanh điều hướng hoặc liên kết **Cấu hình** trong chat:

1. Nhập tên model Ollama đã tải, ví dụ `qwen3:0.6b`.
2. Nhập model Groq và API key của bạn. Mặc định gợi ý `openai/gpt-oss-20b`; có thể thay bằng ID model được tài khoản Groq hỗ trợ.
3. Chọn nhà cung cấp mặc định rồi bấm **Lưu cấu hình**. Trong ô chat, chọn **Local** hoặc **Groq** trước mỗi câu hỏi.

Cấu hình áp dụng riêng cho phiên trình duyệt, gồm cả khách chưa đăng nhập. API key chỉ lưu trong bộ nhớ phiên ở Java; API đọc cấu hình chỉ trả trạng thái đã lưu, không trả lại key. Để trống ô key khi lưu sẽ giữ key cũ; đánh dấu xóa key và chọn Local làm mặc định để gỡ key. Đăng xuất, hết phiên hoặc khởi động lại backend sẽ mất cấu hình. Chưa lưu cấu hình model vào database hay localStorage. Việc lưu xác nhận cấu hình đã được giữ trong phiên, chưa xác minh key/model với Groq.

Groq được gọi từ Python qua HTTPS tại `https://api.groq.com/openai/v1/chat/completions`, dùng Bearer token và JSON mode theo [tài liệu Groq](https://console.groq.com/docs/text-chat). Khi chọn Groq, câu hỏi và các đoạn dữ liệu truy xuất liên quan được gửi ra dịch vụ này; key không được đưa vào prompt, lịch sử chat hay phản hồi về FE. Không ghi key thật vào repository hoặc file ví dụ.

Cả hai chủ đề đều hỗ trợ lựa chọn này: CMC SecOps giữ cơ chế đối chiếu nguồn và streaming; khóa học dùng model để diễn đạt câu trả lời từ kết quả truy xuất, còn danh sách khóa học, giá và quyền học vẫn do hệ thống quyết định. Nếu model lỗi, bị giới hạn hoặc đầu ra không đạt kiểm tra, chat dùng kết quả truy xuất và hiển thị ghi chú. Các kiểm tra dựa trên quy tắc không bảo đảm mọi diễn đạt đều đúng nghĩa.

Groq đã [ngừng hỗ trợ `llama-3.3-70b-versatile` và `llama-3.1-8b-instant` cho Free/Developer từ 16/08/2026](https://console.groq.com/docs/deprecations). Nếu phiên cũ đã lưu một trong hai model này, sửa Model Groq thành `openai/gpt-oss-20b` rồi lưu lại; để trống ô key để giữ key trong phiên. Tài khoản Enterprise có hợp đồng riêng có thể vẫn được dùng model cũ. Việc đổi mặc định của ứng dụng không tự thay lựa chọn đã lưu của người dùng.

GPT-OSS được gọi với reasoning effort `low`, không trả reasoning và có ngân sách ít nhất 1.024 token cho cả reasoning/JSON. Model local giữ giới hạn token riêng như trước. Lỗi Groq được phân loại qua `fallbackReason`: `groq_authentication` (401), `groq_permission_denied` (403), `groq_model_not_found` (404), `groq_model_decommissioned`, `groq_rate_limited` (429), `groq_invalid_request`, `groq_timeout`, `groq_connection_error`, `groq_service_unavailable`. Chat hiển thị nguyên nhân và ghi rõ khi câu trả lời đến từ dữ liệu truy xuất.

Log AI có sự kiện `llm_error` với mã HTTP và mã lỗi thuộc danh sách cho phép; không ghi nguyên thông báo/body lỗi của nhà cung cấp. Khi Groq gửi usage, sự kiện `llm_usage` ghi các số `prompt_tokens`, `completion_tokens`, `total_tokens`. Đây là số token do API báo, có thể bao gồm reasoning; không phải chi phí tiền. Câu trả lời bị bộ kiểm tra nguồn từ chối vẫn có thể đã dùng token. Kiểm tra bằng `docker compose logs --since=10m advisor` rồi tìm `llm_error`/`llm_usage`; lỗi `invalid_generation` khác với lỗi không gọi được API.

`GET /api/chat/config` và `PUT /api/chat/config` dùng phiên Java; ghi cấu hình yêu cầu CSRF. `POST /api/chat/messages` nhận thêm `provider: "local" | "groq"`; bỏ trường này sẽ dùng mặc định của phiên. Java chọn model/key từ phiên và gửi trường `llm` trong request nội bộ tới Python. Client Python cũ bỏ `llm` vẫn dùng hành vi mặc định trước đây. Nếu chạy BE/AI riêng và đổi `AI_LLM_MODEL`, đặt cùng giá trị ở cả hai tiến trình; có thể ghi đè tên local bằng trang cấu hình.

## Cấu trúc dự án

`advisor/app.py` là điểm chạy ASGI; các phần API, cấu hình, nhập dữ liệu, truy xuất, LLM và huấn luyện nằm trong các package riêng. Xem [sơ đồ thư mục, trách nhiệm và nguồn tham khảo](docs/architecture.md). Dữ liệu vẫn ở `data/`, checkpoint TinyGPT ở `artifacts/`, trọng số Qwen do Ollama quản lý bên ngoài repository.

Xem [vận hành bằng Docker, readiness, log/metrics và cấu hình production](docs/operations.md), cùng [bộ đánh giá RAG](evals/README.md). Chưa thiết lập CI theo nhu cầu hiện tại.

## Hỏi đáp tài liệu CMC SecOps

Mở **Trợ lý AI** trên website, chọn **CMC SecOps**, rồi nhập câu hỏi như:

- `Threat Hunting là gì?`
- `Các bảng dữ liệu của Threat Hunting gồm những gì?`
- `Làm sao chạy truy vấn mới trong Threat Hunting?`
- `Một truy vấn trả về tối đa bao nhiêu dòng?`

Kho `data/secops.json` có sẵn bản nội dung tiếng Việt của 6 trang chính thức: SIEM overview, Threat Hunting overview, Run a new query, Saved Queries, SQL User Guide và Search overview. Metadata `fetchedAt` ghi thời điểm nhập thực tế. Chế độ này tìm đoạn tài liệu bằng BM25, hỗ trợ tiếng Việt có/không dấu, rồi dùng model được chọn để tổng hợp câu trả lời kèm nguồn. Câu hỏi tiếp nối sử dụng ngữ cảnh trang vừa hỏi; lịch sử SecOps và khóa học được lưu riêng trong cùng phiên.

Câu `Tính năng Search` hoặc `Search là gì?` được tra trong nhóm tài liệu Search, gồm Query search, Text search, Raw logs và Events. Tên tính năng được nêu rõ sẽ thay ngữ cảnh cũ, nên hỏi Search sau Threat Hunting không tiếp tục dùng nguồn Threat Hunting. Cụm chung `tính năng`/`chức năng` không được tính là bằng chứng khớp nội dung. Nếu kho thiếu trang của tính năng được hỏi, trợ lý trả `not_found`; không dùng một trang khác chỉ vì có cùng từ chung. Ô Search bên trong Saved Queries vẫn thuộc ngữ cảnh Saved Queries. Đây là tra cứu kho đã nhập, chưa tự tìm website trực tuyến theo mỗi câu hỏi.

Luồng mới:

```text
FE → Java /api/chat/messages → Python /v1/advise/stream
  → guardrail đầu vào → BM25 tìm đoạn tài liệu
  → Ollama /api/chat (qwen3:0.6b, thinking=false)
  → kiểm tra JSON, trích dẫn bằng chứng, từ khóa và số liệu
  → Python phát JSON lines (status, delta, result)
  → Java chuyển ngay thành SSE (status, answer_delta)
  → kiểm tra cuối → answer thay thế bản nháp → sources → done → FE
```

`advisor/services/rag.py` điều phối, `advisor/llm/ollama.py` gọi Ollama, `advisor/services/guardrails.py` kiểm tra đầu vào/đầu ra. Model chỉ tổng hợp từ tài liệu đã tìm được; không có công cụ để thực thi SQL hay sửa dữ liệu. Nguồn do mã Python lấy từ kho tài liệu, không lấy URL do model sinh. Guardrail yêu cầu model cung cấp một đoạn bằng chứng có thật trong context, từ chối URL và số liệu mới, đồng thời kiểm tra độ khớp từ khóa và giữ tên `events`/`entities` khi hỏi về bảng. Đây là các kiểm tra theo quy tắc, **không bảo đảm mọi câu trả lời đều đúng nghĩa**; cần đánh giá tiếng Việt và độ bám nguồn trước khi triển khai rộng.

Nếu Ollama chưa chạy, chưa tải model, đang bận, hết thời gian hoặc kết quả không qua kiểm tra, trợ lý trả trích đoạn có nguồn với `answerMode=extractive` và `fallbackReason` trong API Python. Không tìm thấy tài liệu thì trả `not_found` và không gọi LLM. Yêu cầu đổi chỉ dẫn hệ thống bị phát hiện sẽ trả `blocked`. FE phân biệt rõ câu trả lời AI tổng hợp và trích trực tiếp. Model không được tải tự động trong mỗi lần chat.

### Chạy Qwen3 0.6B trên máy local

Cài [Ollama](https://ollama.com/download/windows), sau đó tải model một lần:

```powershell
ollama pull qwen3:0.6b
ollama list
```

Ollama lắng nghe mặc định tại `http://127.0.0.1:11434`. API Python mặc định bật LLM với model `qwen3:0.6b`, context 2.048 token, đầu ra tối đa 256 token, `think=false`, giữ model trong RAM 1 phút sau yêu cầu cuối. Mỗi tiến trình Python chỉ cho một lượt sinh tại một thời điểm; yêu cầu khác nhận trích đoạn thay vì xếp hàng. Chỉ gửi tối đa 2 đoạn, tổng 1.400 ký tự cho model; lịch sử được dùng để tìm tài liệu nhưng không gửi nguyên cuộc trò chuyện. Câu hỏi trên 800 ký tự dùng trích đoạn để giữ ngân sách context.

Model nhỏ và bản lượng tử hóa có thể trả lời sai hoặc bỏ sót ý. Bắt đầu bằng các câu hỏi có đáp án rõ trong nguồn. Không cần OpenAI API key; TinyGPT hiện có vẫn thuộc nhánh tư vấn khóa học.

Cấu hình bằng biến môi trường trước khi chạy `uvicorn`; file `AI/.env.example` là mẫu, không được tự động nạp:

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `AI_LLM_ENABLED` | `true` | `false` để chỉ dùng trích đoạn |
| `AI_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama local; Compose dùng `host.docker.internal` |
| `AI_LLM_MODEL` | `qwen3:0.6b` | Model đã tải trong Ollama |
| `AI_LLM_THINKING` | `false` | Bật thinking nếu model hỗ trợ; không đưa nội dung thinking ra FE |
| `AI_LLM_CONTEXT_TOKENS` | `2048` | Giới hạn 1.024–8.192 token |
| `AI_LLM_MAX_OUTPUT_TOKENS` | `256` | Giới hạn 64–1.024 token, gồm cả JSON/bằng chứng |
| `AI_LLM_TIMEOUT_SECONDS` | `45` | Thời gian chờ model |
| `AI_LLM_KEEP_ALIVE` | `1m` | Thời gian giữ model trong RAM |

Ví dụ tắt model hoặc đổi cấu hình trên PowerShell:

```powershell
$env:AI_LLM_ENABLED = 'false'
.\.venv\Scripts\python.exe -m uvicorn advisor.app:app --host 127.0.0.1 --port 8000
```

`/health` có thêm `llm.enabled`, `llm.model`, `llm.reachable`, `llm.available`, `llm.thinking`, `llm.contextTokens`, `llm.maxOutputTokens`. `available=true` cho biết model đã tải trong Ollama, không có nghĩa model luôn đang nằm trong RAM. Kiểm tra RAM/model đang nạp bằng `ollama ps`.

Java chờ Python tối đa 60 giây (`AI_READ_TIMEOUT_SECONDS`), SSE tối đa 75 giây (`AI_STREAM_TIMEOUT_SECONDS`), proxy FE 90 giây. Nếu tăng timeout LLM, cần tăng đồng bộ các mức này. Ollama được gọi với `stream=true`; Python giải mã phần `answer` từ JSON đang sinh và phát các nhóm từ ngắn sau kiểm tra sơ bộ. Java chuyển tiếp ngay, FE nối `answer_delta` vào bản nháp. Bằng chứng và kiểm tra toàn đáp án chỉ hoàn tất ở cuối; nếu không đạt, sự kiện `answer` thay toàn bộ bản nháp bằng trích đoạn có nguồn. Nội dung đã nhìn thấy trước đó chưa được kiểm chứng đầy đủ. `thinking` và `evidence` không được phát ra giao diện. Đây là streaming trong lúc model đang sinh, không phải chia nhỏ đáp án sau khi sinh xong.

Trong Docker Compose, `advisor` dùng `http://host.docker.internal:11434` để gọi Ollama trên máy host. Ollama cần lắng nghe tại địa chỉ host mà container truy cập được; nếu chỉ bind loopback và kết nối bị từ chối, cấu hình bind riêng theo [hướng dẫn Ollama](https://docs.ollama.com/faq#how-can-i-expose-ollama-on-my-network) hoặc dùng Ollama trong cùng mạng Docker và đặt `AI_OLLAMA_URL=http://ollama:11434`. Không có Ollama thì Compose vẫn chạy bằng trích đoạn. Biến LLM cho Compose nằm trong `BE/.env.example`.

Cập nhật tài liệu từ thư mục `AI`, sau khi cài dependencies:

```powershell
.\.venv\Scripts\python.exe -m advisor.ingestion.documents
```

Trên macOS/Linux, dùng `python -m advisor.ingestion.documents` trong virtualenv. Có thể chỉ định các URL tiếng Việt khác thuộc `/vi/secops/`:

```bash
python -m advisor.ingestion.documents https://docs.cmctelecom.io/vi/secops/siem-overview https://docs.cmctelecom.io/vi/secops/threat-hunting/overview --output data/secops.json
```

Lệnh nhập **thay thế toàn bộ kho** bằng danh sách trang được chỉ định; mặc định là 6 trang nêu trên. Nếu một trang tải/phân tích lỗi, kho cũ được giữ nguyên. Công cụ chỉ tải HTTPS đúng tên miền và đường dẫn CMC SecOps, giới hạn kích thước/thời gian tải, bỏ menu, script, nút điều khiển, liên kết sửa trang và thẻ chuyển sang tài liệu bên cạnh. Nếu website đổi cấu trúc HTML, cần cập nhật bộ phân tích trước khi nhập lại.

Khởi động lại dịch vụ AI sau khi nhập để nạp bản mới. Biến `AI_KNOWLEDGE_PATH` cho phép chọn file kho khác; đường dẫn mặc định được tính từ thư mục mã AI, không phụ thuộc thư mục chạy lệnh. `/health` có `knowledgePages`, `knowledgeChunks`, `knowledgeUpdatedAt`. Docker Compose mount kho từ `AI/data/secops.json`, vì vậy cập nhật file trên máy rồi restart `advisor`.

API `POST /v1/advise` tiếp tục trả JSON đầy đủ cho client cũ. API `POST /v1/advise/stream` trả `application/x-ndjson` cho Java ở chế độ SecOps. Cả hai nhận `"topic": "secops"` và yêu cầu cùng token nội bộ. Phản hồi cuối có `message`, `intent: "documentation"`, `courses: []`, `sources: [{"title": "...", "url": "..."}]`, `answerMode`, `fallbackReason`. `engine=secops-bm25+ollama/qwen3:0.6b` khi sinh bằng model, `secops-bm25` khi trích đoạn. Backend chỉ ghi lịch sử sau khi nhận được kết quả cuối hợp lệ, gửi `sources` riêng và chuyển `engine`/`answerMode` trong `done`. Luồng bị ngắt trước kết quả cuối sẽ không ghi bản nháp vào lịch sử. Bỏ `topic` hoặc dùng `"courses"` để tư vấn khóa học. CSRF vẫn áp dụng giữa FE và BE.

## Chạy local

Dùng Python 3.11 cho môi trường mới. Từ `AI`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m advisor.ingestion.catalog data/courses.example.csv
uvicorn advisor.app:app --host 127.0.0.1 --port 8000
```

Trên Windows, kích hoạt bằng `.venv\Scripts\activate`. Intel macOS dùng wheel PyTorch 2.2.2 vì các bản mới không còn phát hành wheel cho nền tảng này; Linux/Apple Silicon dùng bản 2.6.0 được pin trong requirements. Máy Intel hiện tại đã được kiểm tra với Python 3.9.6; môi trường mới nên dùng Python 3.11.

Chạy BE bằng JDK 21 như README gốc; mặc định gọi AI tại `http://127.0.0.1:8000`. Có thể đặt `AI_SERVICE_URL` và cùng một `AI_SERVICE_TOKEN` cho hai tiến trình. Sau đó chạy FE bằng Node 24.15+ và `npm start`. Mở icon **Trợ lý AI** ở góc phải.

API nội bộ `POST /v1/advise` chỉ dành cho BE. Không publish cổng Python ra Internet. Nếu đặt `AI_SERVICE_TOKEN`, BE gửi header `X-Advisor-Token`. API `/health` cho biết đã nạp checkpoint và bao nhiêu khóa từ file.

## Nhập Excel thật

```bash
python -m advisor.ingestion.catalog /duong-dan/khoa-hoc.xlsx --output data/catalog.json
# Chọn sheet cụ thể nếu cần:
python -m advisor.ingestion.catalog /duong-dan/khoa-hoc.xlsx --sheet Courses
```

Hàng đầu là tên cột. Bắt buộc `slug`, `title`, `price`; cũng chấp nhận **Mã khóa học**, **Tên khóa học**, **Giá**. `slug` là mã duy nhất dạng `python-co-ban`, cùng mã với website nếu khóa đã được bán trên website.

Các cột bổ sung: `level` / Trình độ, `category` / Danh mục, `description` / Mô tả, `instructor` / Giảng viên, `hours` / Thời lượng, `outcomes` / Kết quả đạt được, `audience` / Đối tượng, `prerequisites` / Yêu cầu đầu vào. Tách các đầu ra bằng dấu `|`. File CSV UTF-8 mẫu nằm trong `data/courses.example.csv`; có thể mở bằng Excel và lưu lại thành `.xlsx`.

Giá là số nguyên VND, chấp nhận `499000`, `499.000 ₫`, `499,000 VND`. Không nhận số âm, số lẻ, mã trùng hoặc công thức Excel. Một dòng sai khiến toàn bộ lần nhập bị từ chối; file JSON cũ được giữ nguyên. Giới hạn 5.000 khóa/lần. Khởi động lại dịch vụ AI sau khi nhập để nạp danh mục mới.

Quy tắc dữ liệu:

- Khóa đã có trên website: tên, giá, trình độ, nội dung từ MySQL được ưu tiên. Excel bổ sung đối tượng và yêu cầu đầu vào. Cập nhật giá trên website không cần train lại.
- Khóa chỉ có trong Excel: bot có thể giới thiệu thông tin và giá trong file; FE ghi rõ chưa mở đăng ký và không tạo đường dẫn học/mua.
- Nhập file là cập nhật **kho kiến thức tư vấn**, không tự tạo khóa, bài giảng hay đơn hàng trong MySQL. Muốn mở bán một khóa mới phải có dữ liệu khóa học/bài giảng trên website.

## Mô hình tự xây và huấn luyện

`advisor/training/model.py` chứa **TinyGPT decoder-only Transformer**, tự xây từ các lớp PyTorch: byte tokenizer UTF-8, token/position embeddings, causal multi-head attention, MLP, LayerNorm và language-model head. Khởi tạo trọng số ngẫu nhiên, không tải mô hình hay tokenizer đã huấn luyện.

Có ba chế độ:

1. `text`: pretrain dự đoán byte tiếp theo từ văn bản tiếng Việt; mỗi tài liệu được ngăn bằng một dòng trống.
2. `chat`: huấn luyện tiếp từ hội thoại JSONL có `messages` gồm `role` và `content`; chỉ tính loss trên phần trả lời của assistant.
3. `intents`: học nhận biết sáu ý định `recommend`, `price`, `syllabus`, `open`, `policy`, `greeting`; dùng được trong dịch vụ tư vấn.

Chạy thử huấn luyện từ đầu bằng tập ví dụ nhỏ:

```bash
python -m advisor.training.train --task intents --data data/intents.example.jsonl --epochs 30 --output artifacts/intents.pt
AI_MODEL_PATH=artifacts/intents.pt uvicorn advisor.app:app --host 127.0.0.1 --port 8000
```

Tập ví dụ chỉ để kiểm tra quy trình và học nghiên cứu. Mô hình nhỏ này chưa có khả năng hội thoại tổng quát như LLM thương mại. Khi chưa chỉ định checkpoint, chatbot vẫn hoạt động bằng truy xuất TF-IDF tính với PyTorch và câu trả lời có cấu trúc theo dữ liệu thật. Khi nạp checkpoint intent, dự đoán thử nghiệm của mô hình có thể điều chỉnh cách trả lời giá/nội dung; các quy tắc nghiệp vụ và bộ lọc giá/trình độ vẫn được áp dụng. Trọng số intent không chứa bảng giá.

Để nghiên cứu mô hình sinh văn bản và tiếp tục train bằng dữ liệu riêng:

```bash
python -m advisor.training.train --task text --data /duong-dan/tieng-viet.txt --epochs 10 --output artifacts/pretrain.pt
python -m advisor.training.train --task chat --data /duong-dan/hoi-thoai.jsonl --resume artifacts/pretrain.pt --epochs 10 --output artifacts/chat.pt
python -m advisor.training.generate --checkpoint artifacts/chat.pt --prompt '<user>
Tôi muốn học Python
<assistant>
' --max-tokens 150
```

Tùy chọn `--device cuda` hoặc `--device mps` nếu thiết bị và bản PyTorch hỗ trợ; mặc định CPU. Có thể tăng `--width`, `--layers`, `--heads`, `--context` cho lần khởi tạo mới. `--resume` nạp lại trọng số/config, khởi tạo optimizer mới để huấn luyện tiếp, không phải khôi phục chính xác toàn bộ trạng thái một lần chạy bị ngắt.

Train/validation chia theo hash cố định của câu hỏi/tài liệu, loại trùng trước khi chia. Mỗi epoch báo validation loss, perplexity và intent accuracy khi phù hợp; lưu checkpoint có validation loss thấp nhất. Cần thêm tập test riêng và các cuộc tư vấn đã được duyệt để đánh giá trước khi dùng thực tế. Validation trên tập ví dụ nhỏ không chứng minh chất lượng trên khách hàng thật. Không tự động đưa hội thoại khách vào tập train.

Checkpoint `text`/`chat` dùng để nghiên cứu sinh văn bản qua CLI; dịch vụ bán khóa học chỉ nhận checkpoint `intents`, tránh dùng văn bản chưa kiểm chứng làm giá hoặc quyết định cấp quyền học. Có thể phát triển tiếp cách sinh câu trả lời sau khi có đủ dữ liệu và đánh giá phù hợp.

## SSE và thao tác khóa học

FE dùng `fetch` POST, gửi cookie và CSRF token, đọc `status`, `answer_delta`, `answer`, `courses`, `sources`, `done`, `error`. `answer_delta` nối nội dung trong khi Qwen đang sinh; `answer` thay thế bằng đáp án cuối đã kiểm tra hoặc trích đoạn dự phòng. Nginx đã tắt buffering. Khi mất kết nối hoặc nhận `error`, FE xóa bản nháp chưa hoàn tất và cho phép gửi lại câu hỏi.

BE giữ tối đa 12 lượt user/assistant trong phiên, giới hạn 20 câu hỏi/phút/phiên và một yêu cầu đang chạy/phiên. Bộ giới hạn này dành cho phạm vi ứng dụng hiện tại; khi mở public cần bổ sung giới hạn ở gateway để không phụ thuộc riêng vào cookie phiên.

Thẻ khóa học có nút Xem khóa học, Đăng ký hoặc Vào học. Bot không gọi checkout hay tạo quyền học. Người dùng thực hiện quy trình checkout hiện có; backend tiếp tục kiểm tra đăng nhập và quyền với API bài học.

## Docker

Từ thư mục gốc:

```bash
docker compose -f BE/compose.yaml up -d --build
docker compose -f FE/compose.yaml up -d --build
```

Compose BE chạy thêm `advisor` trong mạng nội bộ, không mở port AI ra máy host. `AI/data` và `AI/artifacts` được mount read-only vào container; nhập file hoặc train bằng CLI bên ngoài rồi restart advisor. Để dùng checkpoint intent, đặt `AI_MODEL_PATH=/app/artifacts/intents.pt` trong `BE/.env`, sau đó chạy lại Compose.

## Kiểm tra

```bash
python -m pytest -q
ruff format --check .
ruff check .
# Từ thư mục gốc khi BE và AI đang chạy:
node scripts/chat-smoke.mjs http://127.0.0.1:8080
# Yêu cầu lượt hỏi Threat Hunting thực sự đi qua Qwen/Ollama:
node scripts/chat-smoke.mjs http://127.0.0.1:8080 --require-llm
```

Các test kiểm tra bộ lọc giá/trình độ, chuyển chủ đề, dữ liệu website ưu tiên Excel, giá lỗi và mã trùng, token dịch vụ, causal attention không nhìn tương lai, cập nhật trọng số thật và lưu/nạp checkpoint.
