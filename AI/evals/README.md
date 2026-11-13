# Đánh giá RAG

`secops.json` chứa bộ hồi quy ban đầu: câu hỏi tiếng Việt có/không dấu, câu hỏi tiếp nối, định nghĩa, thao tác, giới hạn số liệu, ngoài phạm vi và yêu cầu vượt chỉ dẫn. Mỗi câu trả lời được có nguồn/heading chuẩn, ý bắt buộc, ý cấm khi cần, và đáp án tham khảo để người duyệt đối chiếu.

## Chạy local

Từ thư mục `AI`, sau khi cài requirements:

```powershell
python -m advisor.evaluation.runner --mode retrieval --output evals/reports/retrieval.json
python -m advisor.evaluation.runner --mode rag --output evals/reports/qwen.json
```

`retrieval` không gọi Ollama, kiểm tra nguồn tìm được và đáp án trích đoạn. `rag` gọi Qwen thật qua cùng luồng RAG/stream như sản phẩm, chấm đáp án cuối; cần Ollama và model đã tải. Nếu model lỗi/bận hoặc kiểm tra không đạt, kết quả được ghi là trích đoạn với lý do fallback, không tính là đáp án generated đạt chất lượng.

Chạy bộ đánh giá trong image hiện tại, từ thư mục `BE`:

```powershell
docker compose exec advisor python -m advisor.evaluation.runner --mode retrieval
docker compose exec advisor python -m advisor.evaluation.runner --mode rag
```

Không chạy đánh giá model đồng thời với traffic thật trên máy ít RAM/CPU. Container hiện chạy user không có quyền ghi vào thư mục mã; nếu cần báo cáo, chạy local với `--output` hoặc mount một thư mục report có quyền ghi.

## Chỉ số và ngưỡng

- `casePassRate`: tỷ lệ câu vượt tất cả kiểm tra tự động.
- `retrievalHitRate`: tỷ lệ câu có đáp án tìm được đúng các nguồn và heading đã gán nhãn.
- `generatedRate`: tỷ lệ câu có đáp án trả bằng model, tách biệt với fallback.
- `generatedChecksPassRate`: tỷ lệ đáp án generated vượt các kiểm tra hồi quy; null khi không có đáp án generated.
- `abstentionAccuracy`, `blockedAccuracy`: biết từ chối câu ngoài phạm vi và chặn các mẫu vượt chỉ dẫn trong dataset.
- `latencyP95Seconds`: phân vị 95% thời gian đáp án cuối của bộ câu hỏi này.

Mặc định `--min-pass-rate 1.0`; không đạt trả exit code 1. Dữ liệu/cấu hình không hợp lệ trả exit code 2. Khi cần yêu cầu model thực sự sinh cho một tỷ lệ tối thiểu, đặt thêm `--min-generated-rate`, ví dụ `--mode rag --min-generated-rate 0.5`. Ngưỡng cần chọn theo mục tiêu sản phẩm; bộ đánh giá không mặc định coi mọi fallback là lỗi.

Report lưu hash dataset, revision kho, thời điểm nhập, cấu hình model, thời gian và kết quả từng câu. `evals/reports/` bị Git/Docker ignore. Cần ghi lại digest model (`ollama list`) cùng báo cáo khi so sánh giữa các máy vì một model tag có thể thay đổi.

## Giới hạn và cách mở rộng

Kiểm tra `requiredFacts`/`forbiddenFacts` dựa trên chuỗi và ranh giới từ sau chuẩn hóa tiếng Việt. Đây là kiểm tra hồi quy, **không phải đánh giá ngữ nghĩa tự động**: có thể bỏ sót suy luận sai, phủ định, hoặc đánh trượt cách diễn đạt tương đương. Không dùng tỷ lệ pass này làm cam kết độ chính xác tổng quát.

Trước khi đưa ra nhiều người dùng, bổ sung câu hỏi thực tế đã loại dữ liệu cá nhân, biến thể diễn đạt, câu dễ nhầm và câu không có đáp án. Gán nhãn dựa trên tài liệu nguồn trước khi xem output model. Người duyệt cần kiểm tra từng khẳng định có được nguồn hỗ trợ, trả lời đủ ý và không bịa. Giữ một tập câu hỏi riêng chưa dùng để chỉnh prompt/retrieval; bộ hiện tại là tập hồi quy nhỏ, chưa phải benchmark độc lập.

Tham khảo cách tách [đánh giá truy xuất và độ bám nguồn trong RAG](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/rag-evaluators). Chưa dùng dịch vụ đánh giá trả phí hoặc API bên ngoài.
