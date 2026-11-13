export interface ModelStatus {
  answerMode?: string;
  engine?: string;
  modelLabel?: string;
  fallbackReason?: string;
}

export function answerModelLabel(status: ModelStatus): string {
  if (!status.answerMode) return `Đang xử lý · ${status.modelLabel || 'AI'}`;
  if (status.answerMode === 'generated') {
    for (const [provider, label] of [
      ['groq', 'Groq'],
      ['ollama', 'Local'],
    ]) {
      const prefix = `+${provider}/`;
      const index = status.engine?.indexOf(prefix) ?? -1;
      if (index >= 0) return `${label} · ${status.engine!.slice(index + prefix.length)}`;
    }
    return 'AI tổng hợp';
  }
  return status.answerMode === 'extractive' || status.answerMode === 'course'
    ? 'Dữ liệu truy xuất'
    : 'Trợ lý';
}

export function modelFailureMessage(reason?: string): string {
  if (!reason) return '';
  const messages: Record<string, string> = {
    groq_model_decommissioned: 'Model Groq đã ngừng hỗ trợ. Hãy đổi model trong Cấu hình model.',
    groq_authentication:
      'Groq từ chối API key (401). Hãy kiểm tra hoặc thay key trong Cấu hình model.',
    groq_permission_denied:
      'Groq từ chối quyền truy cập (403). Hãy kiểm tra quyền model của tài khoản và project.',
    groq_model_not_found:
      'Không tìm thấy model Groq hoặc tài khoản chưa được cấp quyền (404). Hãy kiểm tra Model ID.',
    groq_rate_limited: 'Groq đã chạm giới hạn lượt gọi hoặc token (429). Hãy chờ rồi thử lại.',
    groq_invalid_request:
      'Groq từ chối tham số yêu cầu. Hãy kiểm tra model có hỗ trợ JSON mode và các tham số đang dùng.',
    groq_timeout: 'Đã hết thời gian chờ Groq. Hãy thử lại sau.',
    groq_connection_error:
      'Dịch vụ AI chưa kết nối được tới Groq. Hãy kiểm tra mạng và kết nối HTTPS.',
    groq_service_unavailable: 'Dịch vụ Groq đang không sẵn sàng. Hãy thử lại sau.',
    model_busy: 'Model đang xử lý yêu cầu khác. Hãy thử lại sau.',
    disabled: 'Model local đang bị tắt trong cấu hình dịch vụ AI.',
    context_budget: 'Câu hỏi vượt giới hạn ngữ cảnh dành cho model.',
    invalid_generation: 'Model đã phản hồi nhưng nội dung chưa qua kiểm tra nguồn hoặc định dạng.',
    model_unavailable: 'Không gọi được model đã chọn. Hãy kiểm tra cấu hình và kết nối.',
  };
  return messages[reason] || 'Model đã chọn chưa tạo được câu trả lời phù hợp.';
}
