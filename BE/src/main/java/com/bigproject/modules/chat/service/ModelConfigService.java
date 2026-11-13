package com.bigproject.modules.chat.service;

import com.bigproject.modules.chat.dto.ModelConfigRequest;
import jakarta.servlet.http.HttpSession;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class ModelConfigService {
  private static final String CONFIG = ModelConfigService.class.getName();
  private final String localModel;

  public ModelConfigService(@Value("${app.ai.local-model:qwen3:0.6b}") String localModel) {
    this.localModel = localModel;
  }

  public View read(HttpSession session) {
    synchronized (session) {
      return configuration(session).view();
    }
  }

  public View save(HttpSession session, ModelConfigRequest request) {
    if (request.localModel().endsWith("-cloud")) {
      throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Hãy chọn model Ollama local.");
    }
    synchronized (session) {
      var previous = configuration(session);
      boolean removeKey = Boolean.TRUE.equals(request.removeGroqApiKey());
      String key = removeKey ? "" : previous.apiKey();
      if (!removeKey && request.groqApiKey() != null && !request.groqApiKey().isBlank()) {
        key = request.groqApiKey();
      }
      if ("groq".equals(request.defaultProvider()) && key.isBlank()) {
        throw new ResponseStatusException(
            HttpStatus.BAD_REQUEST, "Groq cần API key. Hãy nhập key hoặc chọn Local làm mặc định.");
      }
      var next =
          new Configuration(
              request.defaultProvider(), request.localModel(), request.groqModel(), key);
      session.setAttribute(CONFIG, next);
      return next.view();
    }
  }

  public Selection select(HttpSession session, String provider) {
    synchronized (session) {
      var config = configuration(session);
      String selected = provider == null ? config.defaultProvider() : provider;
      if ("groq".equals(selected) && config.apiKey().isBlank()) {
        throw new ResponseStatusException(
            HttpStatus.BAD_REQUEST, "Hãy cấu hình API key Groq ở trang Cấu hình model trước.");
      }
      return new Selection(
          selected,
          "groq".equals(selected) ? config.groqModel() : config.localModel(),
          "groq".equals(selected) ? config.apiKey() : null);
    }
  }

  private Configuration configuration(HttpSession session) {
    var config = (Configuration) session.getAttribute(CONFIG);
    return config == null
        ? new Configuration("local", localModel, "openai/gpt-oss-20b", "")
        : config;
  }

  private record Configuration(
      String defaultProvider, String localModel, String groqModel, String apiKey) {
    View view() {
      return new View(defaultProvider, localModel, groqModel, !apiKey.isBlank());
    }

    @Override
    public String toString() {
      return "ModelConfiguration[credentials=redacted]";
    }
  }

  public record View(
      String defaultProvider, String localModel, String groqModel, boolean groqConfigured) {}

  public record Selection(String provider, String model, String apiKey) {
    @Override
    public String toString() {
      return "ModelSelection[provider=" + provider + ", model=" + model + ", credentials=redacted]";
    }
  }
}
