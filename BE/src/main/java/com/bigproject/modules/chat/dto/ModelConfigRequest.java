package com.bigproject.modules.chat.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record ModelConfigRequest(
    @NotBlank @Pattern(regexp = "local|groq") String defaultProvider,
    @NotBlank @Pattern(regexp = "[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,149}") String localModel,
    @NotBlank @Pattern(regexp = "[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,149}") String groqModel,
    @Size(max = 256) @Pattern(regexp = "[\\x21-\\x7E]*") String groqApiKey,
    Boolean removeGroqApiKey) {
  @Override
  public String toString() {
    return "ModelConfigRequest[credentials=redacted]";
  }
}
