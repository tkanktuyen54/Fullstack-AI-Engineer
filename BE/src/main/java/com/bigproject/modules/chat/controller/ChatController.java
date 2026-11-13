package com.bigproject.modules.chat.controller;

import com.bigproject.core.security.CurrentUser;
import com.bigproject.modules.chat.dto.ChatRequest;
import com.bigproject.modules.chat.service.ChatService;
import com.bigproject.modules.chat.service.ModelConfigService;
import jakarta.servlet.http.HttpSession;
import jakarta.validation.Valid;
import java.io.IOException;
import java.time.Duration;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
public class ChatController {
  private final ChatService chat;
  private final ModelConfigService config;
  private final long streamTimeoutMillis;

  public ChatController(
      ChatService chat,
      ModelConfigService config,
      @Value("${app.ai.stream-timeout-seconds:75}") long streamTimeoutSeconds) {
    this.chat = chat;
    this.config = config;
    this.streamTimeoutMillis = Duration.ofSeconds(streamTimeoutSeconds).toMillis();
  }

  @PostMapping(value = "/api/chat/messages", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
  public SseEmitter message(
      @Valid @RequestBody ChatRequest request,
      HttpSession session,
      @AuthenticationPrincipal CurrentUser user) {
    var selection = config.select(session, request.provider());
    var state = chat.begin(session);
    var emitter = new SseEmitter(streamTimeoutMillis);
    Thread.ofVirtual()
        .name("ai-assistant")
        .start(
            () -> {
              try {
                emitter.send(
                    SseEmitter.event()
                        .name("status")
                        .data(
                            Map.of(
                                "message",
                                "secops".equals(request.topic())
                                    ? "Đang tra cứu tài liệu và tạo câu trả lời…"
                                    : "Đang tìm khóa học phù hợp…")));
                var reply =
                    chat.answer(
                        request,
                        state,
                        user == null ? null : user.id(),
                        selection,
                        (event, data) -> emitter.send(SseEmitter.event().name(event).data(data)));
                emitter.send(
                    SseEmitter.event().name("answer").data(Map.of("text", reply.message())));
                emitter.send(SseEmitter.event().name("courses").data(reply.courses()));
                emitter.send(SseEmitter.event().name("sources").data(reply.sources()));
                emitter.send(
                    SseEmitter.event()
                        .name("done")
                        .data(
                            Map.of(
                                "intent",
                                reply.intent(),
                                "engine",
                                reply.engine(),
                                "answerMode",
                                reply.answerMode(),
                                "fallbackReason",
                                reply.fallbackReason())));
                emitter.complete();
              } catch (Exception ex) {
                try {
                  String message =
                      ex instanceof ResponseStatusException status
                          ? status.getReason()
                          : "Trợ lý chưa trả lời được. Bạn thử lại nhé.";
                  emitter.send(SseEmitter.event().name("error").data(Map.of("message", message)));
                  emitter.complete();
                } catch (IOException | IllegalStateException disconnected) {
                  emitter.completeWithError(disconnected);
                }
              } finally {
                chat.finish(state);
              }
            });
    return emitter;
  }
}
