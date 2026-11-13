# Vận hành dịch vụ AI bằng Docker

Giữ Docker Compose hiện tại tại `BE/compose.yaml`; chưa thiết lập CI. Dịch vụ AI không publish port ra host, BE gọi qua mạng nội bộ. Qwen vẫn do Ollama bên ngoài container quản lý.

## Build và chạy

Từ thư mục `BE`:

```powershell
docker compose up -d --build advisor
docker compose ps advisor
docker compose logs --tail 100 advisor
```

Chỉ build/recreate dịch vụ AI. Không dùng `down -v`; volume MySQL không cần thay đổi. Container chạy bằng user `advisor`, tự khởi động lại khi tiến trình thoát, giới hạn RAM mặc định 2 GiB và xoay vòng log 3 file, mỗi file 10 MiB. `AI_MEMORY_LIMIT` thay giới hạn RAM container; giới hạn này **không bao gồm Ollama chạy trên host**. Healthcheck Compose kiểm tra readiness; trạng thái unhealthy không tự kích hoạt restart của Docker khi tiến trình vẫn còn sống.

## Cấu hình production

Các biến Compose lấy từ `BE/.env` hoặc môi trường shell. Tạo token ngẫu nhiên bằng `python -c "import secrets; print(secrets.token_urlsafe(32))"`, lưu riêng ngoài Git và đặt cùng token cho BE và Python:

```dotenv
AI_ENVIRONMENT=production
AI_SERVICE_TOKEN=<token-ngau-nhien-it-nhat-32-ky-tu>
AI_REQUIRE_KNOWLEDGE=true
AI_READINESS_REQUIRE_LLM=false
AI_MAX_ACTIVE_REQUESTS=8
AI_MEMORY_LIMIT=2g
```

Khi đổi token của hệ thống đang chạy, recreate cả `backend` và `advisor` để hai bên dùng cùng giá trị. Không đưa token vào lệnh hoặc log công khai. File `.env` không được Python tự nạp khi chạy native; cần export biến trước khi chạy Uvicorn. Production thiếu token hoặc token ngắn hơn 32 ký tự sẽ không khởi động.

`AI_STREAM_VALIDATION` mặc định `incremental` ở development và `complete` ở production. `incremental` phát bản nháp sau kiểm tra sơ bộ rồi thay bằng đáp án cuối; người dùng có thể đọc nội dung chưa qua kiểm tra cuối. `complete` vẫn phát trạng thái xử lý ngay, giữ text đến khi kiểm tra bằng chứng hoàn tất rồi phát đáp án. Cả hai chế độ vẫn dùng Ollama `stream=true` và giữ nguyên hợp đồng NDJSON → BE SSE → FE. Nếu chạy native có thể export biến này để chọn chế độ; Compose hiện dùng mặc định theo môi trường. Các kiểm tra hiện tại vẫn là quy tắc, không bảo đảm đúng nghĩa; xem [đánh giá RAG](../evals/README.md).

## Healthcheck

| Endpoint | Ý nghĩa |
| --- | --- |
| `/health/live` | Tiến trình phục vụ HTTP, không gọi Ollama |
| `/health/ready` | HTTP 200 khi đáp ứng các thành phần bắt buộc, HTTP 503 khi chưa đáp ứng |
| `/health` | Thông tin chẩn đoán tương thích cũ, gồm revision SHA-256 của nội dung kho |

Mặc định LLM không bắt buộc cho readiness vì hệ thống có thể trả trích đoạn. Ollama lỗi/thiếu model: readiness trả HTTP 200 với `status=degraded`. Đặt `AI_READINESS_REQUIRE_LLM=true` nếu sản phẩm yêu cầu có LLM mới nhận traffic; khi đó trả 503 nếu không truy cập được hoặc chưa tải model. Đặt `AI_REQUIRE_KNOWLEDGE=true` cho sản phẩm SecOps để kho thiếu/rỗng làm readiness trả 503. Nếu chỉ dùng tư vấn khóa học, có thể đặt false.

`llm.available` kiểm tra model có trong Ollama, không chạy sinh thử và không bảo đảm model đang ở RAM. Khi warm-up, phần sinh vẫn có thể timeout và chuyển sang trích đoạn.

## Log và metrics

Ứng dụng ghi JSON vào stderr: `http_request`, `http_error`, `rag_answer`, `stream_error`, `service_started`. Không ghi câu hỏi, lịch sử, đáp án, service token hoặc nội dung exception từ upstream. Tắt/định tuyến access log mặc định của Uvicorn riêng nếu triển khai có thể gửi dữ liệu cá nhân qua query string; API chat hiện nhận dữ liệu qua POST body.

Mỗi response có `X-Request-ID`; chấp nhận ID đầu vào gồm 1–64 ký tự chữ, số, dấu chấm, gạch dưới hoặc gạch ngang, nếu không hợp lệ thì tạo ID mới. BE/proxy cần chuyển tiếp cùng header để đối chiếu log xuyên dịch vụ; BE hiện chưa tự truyền ID này. ID không được dùng làm nhãn metrics.

`GET /metrics` xuất định dạng Prometheus và dùng cùng `X-Advisor-Token` như API nếu có cấu hình token. Ví dụ đọc metrics bên trong container mà không in token:

```powershell
docker compose exec advisor python -c "import os,urllib.request; r=urllib.request.Request('http://127.0.0.1:8000/metrics',headers={'X-Advisor-Token':os.environ.get('AI_SERVICE_TOKEN','')}); print(urllib.request.urlopen(r).read().decode())"
```

Các chỉ số chính:

- `advisor_http_requests_total`, `advisor_http_duration_seconds`: đếm request và thời gian đến cuối response/stream; stream bị hủy ghi `status=incomplete`.
- `advisor_active_requests`: số advice request đang xử lý.
- `advisor_retrieval_seconds`, `advisor_first_answer_seconds`: thời gian tìm tài liệu và đến đoạn đáp án đầu tiên, không tính status là text đáp án.
- `advisor_answers_total{mode,reason}`: đáp án cuối theo chế độ và nguyên nhân fallback.
- `advisor_stream_errors_total`: lỗi sau khi stream đã gửi header, kể cả khi HTTP vẫn là 200.

Registry và giới hạn request áp dụng **từng tiến trình**. Chạy mặc định một worker; chưa có điều phối chung giữa nhiều worker/replica. `AI_MAX_ACTIVE_REQUESTS` giới hạn toàn bộ advice request đến khi response đóng, quá giới hạn trả 429 và `Retry-After: 1`. LLM vẫn chỉ nhận một lượt sinh mỗi tiến trình; các lượt khác trả trích đoạn thay vì tạo hàng đợi. Cần đo tải trước khi tăng concurrency; tăng worker không đồng nghĩa tăng khả năng sinh của Ollama.

## Cập nhật và khôi phục kho tài liệu

Kho được nạp một lần lúc startup. Import có lỗi giữ kho cũ và chỉ thay file sau khi tải xong. Trước một lần import, lưu bản JSON cũ vào nơi backup ngoài Git; sau import chạy đánh giá retrieval với kho mới, kiểm tra thủ công các phần thay đổi, rồi restart `advisor`. Nếu chất lượng giảm, khôi phục file backup và restart lại. `/health.knowledgeRevision` và manifest báo cáo đánh giá giúp đối chiếu chính xác nội dung đang dùng. Hiện chưa có scheduler, version store hoặc hot reload tự động.

## Tham khảo

- [FastAPI deployment concepts](https://fastapi.tiangolo.com/deployment/concepts/): readiness/vận hành cần xét bộ nhớ, tiến trình và khả năng restart.
- [Prometheus exposition format](https://prometheus.io/docs/instrumenting/exposition_formats/): định dạng endpoint metrics.
- [Ollama concurrency](https://docs.ollama.com/faq#how-does-ollama-handle-concurrent-requests): số lượt song song ảnh hưởng tài nguyên và hàng đợi model.
