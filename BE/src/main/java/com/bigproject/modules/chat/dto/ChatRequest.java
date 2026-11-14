package com.bigproject.modules.chat.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record ChatRequest(
    @NotBlank(message = "Bạn hãy nhập câu hỏi.")
        @Size(max = 2000, message = "Câu hỏi tối đa 2.000 ký tự.")
        String message,
    @Pattern(regexp = "[a-z0-9-]{1,150}", message = "Mã khóa học không hợp lệ.") String courseSlug,
    @Pattern(regexp = "courses|secops|employees", message = "Chủ đề trò chuyện không hợp lệ.")
        String topic,
    @Pattern(regexp = "local|groq", message = "Nhà cung cấp model không hợp lệ.") String provider) {
  @Override
  public String toString() {
    return "ChatRequest[redacted]";
  }
}
