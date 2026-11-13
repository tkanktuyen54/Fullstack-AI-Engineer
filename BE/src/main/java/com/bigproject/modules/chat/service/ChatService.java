package com.bigproject.modules.chat.service;

import com.bigproject.modules.chat.dto.ChatRequest;
import com.bigproject.modules.course.entity.Course;
import com.bigproject.modules.course.service.CourseService;
import com.bigproject.modules.enrollment.repository.EnrollmentRepository;
import jakarta.servlet.http.HttpSession;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.math.BigDecimal;
import java.net.URI;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.ObjectMapper;

@Service
public class ChatService {
  private static final String STATE = ChatService.class.getName();
  private final CourseService courses;
  private final EnrollmentRepository enrollments;
  private final RestClient ai;
  private final ObjectMapper json;

  public ChatService(
      CourseService courses,
      EnrollmentRepository enrollments,
      ObjectMapper json,
      @Value("${app.ai.base-url:http://127.0.0.1:8000}") String baseUrl,
      @Value("${app.ai.token:}") String token,
      @Value("${app.ai.read-timeout-seconds:60}") long readTimeoutSeconds) {
    this.courses = courses;
    this.enrollments = enrollments;
    this.json = json;
    var factory =
        new JdkClientHttpRequestFactory(
            HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(3))
                .build());
    factory.setReadTimeout(Duration.ofSeconds(readTimeoutSeconds));
    ai =
        RestClient.builder()
            .baseUrl(baseUrl)
            .requestFactory(factory)
            .defaultHeader("X-Advisor-Token", token)
            .build();
  }

  public State begin(HttpSession session) {
    synchronized (session) {
      var state = (State) session.getAttribute(STATE);
      if (state == null) {
        state = new State();
        session.setAttribute(STATE, state);
      }
      synchronized (state) {
        long now = System.currentTimeMillis();
        if (now - state.windowStart >= 60_000) {
          state.windowStart = now;
          state.requests = 0;
        }
        if (state.busy || state.requests >= 20) {
          throw new ResponseStatusException(
              HttpStatus.TOO_MANY_REQUESTS, "Bạn hãy chờ câu trả lời hoặc thử lại sau một phút.");
        }
        state.requests++;
        state.busy = true;
        return state;
      }
    }
  }

  public Reply answer(
      ChatRequest request,
      State state,
      Long userId,
      ModelConfigService.Selection selection,
      Progress progress) {
    String topic = request.topic() == null ? "courses" : request.topic();
    List<Course> catalog = "courses".equals(topic) ? courses.list("", "") : List.of();
    List<Turn> history;
    synchronized (state) {
      history = List.copyOf(state.history.getOrDefault(topic, List.of()));
    }
    AiReply result;
    try {
      var body =
          new AiRequest(
              request.message(), request.courseSlug(), topic, history, catalog, selection);
      result =
          "secops".equals(topic)
              ? streamAi(body, progress)
              : ai.post().uri("/v1/advise").body(body).retrieve().body(AiReply.class);
    } catch (RestClientException ex) {
      throw new ResponseStatusException(
          HttpStatus.SERVICE_UNAVAILABLE, "Trợ lý đang chưa kết nối được. Bạn thử lại sau nhé.");
    }
    if (result == null
        || result.message() == null
        || result.message().isBlank()
        || result.courses() == null
        || result.message().length() > 12000) {
      throw new ResponseStatusException(
          HttpStatus.BAD_GATEWAY, "Trợ lý chưa trả lời được. Bạn thử lại nhé.");
    }
    Map<String, Course> live =
        catalog.stream().collect(Collectors.toMap(Course::slug, Function.identity()));
    List<Suggestion> suggestions = new ArrayList<>();
    for (AiCourse item :
        result.courses().stream().filter(item -> "courses".equals(topic)).limit(3).toList()) {
      if (item == null || item.slug() == null || !item.slug().matches("[a-z0-9-]{1,150}")) {
        continue;
      }
      Course course = live.get(item.slug());
      if (course != null) {
        boolean enrolled = userId != null && enrollments.exists(userId, course.id());
        suggestions.add(
            new Suggestion(
                course.slug(),
                course.title(),
                course.price(),
                course.level(),
                item.reason(),
                true,
                enrolled));
      } else if (item.title() != null && item.price() != null && item.price().signum() >= 0) {
        suggestions.add(
            new Suggestion(
                item.slug(),
                item.title(),
                item.price(),
                item.level(),
                item.reason(),
                false,
                false));
      }
    }
    List<Source> sources =
        result.sources() == null
            ? List.of()
            : result.sources().stream().filter(ChatService::validSource).limit(3).toList();
    synchronized (state) {
      var turns = state.history.computeIfAbsent(topic, key -> new ArrayList<>());
      turns.add(new Turn("user", request.message()));
      turns.add(new Turn("assistant", result.message()));
      while (turns.size() > 12) {
        turns.removeFirst();
      }
    }
    return new Reply(
        result.message(),
        result.intent(),
        suggestions,
        sources,
        result.engine() == null ? "unknown" : result.engine(),
        result.answerMode() == null
            ? ("secops".equals(topic) ? "extractive" : "course")
            : result.answerMode(),
        result.fallbackReason() == null ? "" : result.fallbackReason());
  }

  private AiReply streamAi(AiRequest body, Progress progress) {
    return ai.post()
        .uri("/v1/advise/stream")
        .accept(MediaType.parseMediaType("application/x-ndjson"))
        .body(body)
        .exchange(
            (request, response) -> {
              if (!response.getStatusCode().is2xxSuccessful()) {
                throw new RestClientException("AI stream request failed");
              }
              var contentType = response.getHeaders().getContentType();
              if (contentType == null
                  || !contentType.isCompatibleWith(
                      MediaType.parseMediaType("application/x-ndjson"))) {
                throw new RestClientException("AI did not return a JSON lines stream");
              }
              AiReply result = null;
              int frames = 0;
              int characters = 0;
              try (var reader =
                  new BufferedReader(
                      new InputStreamReader(response.getBody(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                  if (line.isBlank()) continue;
                  if (line.length() > 50_000 || ++frames > 2048 || result != null) {
                    throw new RestClientException("Invalid AI stream size or completion");
                  }
                  var event = json.readValue(line, AiStreamEvent.class);
                  switch (event.type() == null ? "" : event.type()) {
                    case "status" -> {
                      if (event.message() == null || event.message().length() > 500) {
                        throw new RestClientException("Invalid status frame");
                      }
                      progress.send("status", Map.of("message", event.message()));
                    }
                    case "delta" -> {
                      if (event.text() == null || (characters += event.text().length()) > 12000) {
                        throw new RestClientException("Invalid answer delta");
                      }
                      progress.send("answer_delta", Map.of("text", event.text()));
                    }
                    case "result" -> result = event.reply();
                    default ->
                        throw new RestClientException(
                            "AI stream failed or returned an unknown frame");
                  }
                }
              }
              if (result == null)
                throw new RestClientException("AI stream ended without a final result");
              return result;
            });
  }

  @FunctionalInterface
  public interface Progress {
    void send(String event, Object data) throws IOException;
  }

  public record AiStreamEvent(String type, String message, String text, AiReply reply) {}

  private static boolean validSource(Source source) {
    if (source == null
        || source.title() == null
        || source.title().isBlank()
        || source.title().length() > 500
        || source.url() == null
        || source.url().length() > 2000) {
      return false;
    }
    try {
      URI uri = URI.create(source.url());
      return "https".equals(uri.getScheme())
          && "docs.cmctelecom.io".equals(uri.getHost())
          && uri.getUserInfo() == null
          && uri.getPort() == -1
          && uri.getQuery() == null
          && uri.getPath() != null
          && uri.getPath().startsWith("/vi/secops/")
          && !uri.getPath().contains("\\")
          && Arrays.stream(uri.getPath().split("/"))
              .noneMatch(segment -> ".".equals(segment) || "..".equals(segment))
          && uri.normalize().getPath().equals(uri.getPath());
    } catch (IllegalArgumentException ex) {
      return false;
    }
  }

  public void finish(State state) {
    synchronized (state) {
      state.busy = false;
    }
  }

  public static class State {
    private long windowStart = System.currentTimeMillis();
    private int requests;
    private boolean busy;
    private final Map<String, List<Turn>> history = new HashMap<>();
  }

  public record Turn(String role, String content) {}

  public record AiRequest(
      String message,
      String courseSlug,
      String topic,
      List<Turn> history,
      List<Course> courses,
      ModelConfigService.Selection llm) {
    @Override
    public String toString() {
      return "AiRequest[redacted]";
    }
  }

  public record AiCourse(
      String slug, String title, BigDecimal price, String level, String reason) {}

  public record AiReply(
      String message,
      String intent,
      List<AiCourse> courses,
      List<Source> sources,
      String engine,
      String answerMode,
      String fallbackReason) {}

  public record Source(String title, String url) {}

  public record Suggestion(
      String slug,
      String title,
      BigDecimal price,
      String level,
      String reason,
      boolean available,
      boolean enrolled) {}

  public record Reply(
      String message,
      String intent,
      List<Suggestion> courses,
      List<Source> sources,
      String engine,
      String answerMode,
      String fallbackReason) {}
}
