package com.bigproject;

import static org.assertj.core.api.Assertions.assertThat;

import com.bigproject.modules.auth.dto.RegisterRequest;
import com.bigproject.modules.auth.service.AuthService;
import com.bigproject.modules.employee.mcp.EmployeeMcpConfig;
import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@SpringBootTest(
    webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
    properties =
        "spring.datasource.url=jdbc:h2:mem:employee-mcp;MODE=MySQL;DATABASE_TO_LOWER=TRUE;DB_CLOSE_DELAY=-1")
@ActiveProfiles("test")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class EmployeeMcpIntegrationTests {
  @LocalServerPort int port;
  @Autowired JdbcTemplate jdbc;
  @Autowired ObjectMapper json;
  @Autowired AuthService auth;
  private Actor hr;
  private Actor student;

  @BeforeAll
  void seed() throws Exception {
    hr = actor("HR");
    student = actor(null);
    for (int i = 1; i <= 12; i++) {
      jdbc.update(
          """
          INSERT INTO employee(public_id, employee_code, full_name, department, position,
            status, profile_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
          """,
          UUID.randomUUID().toString(),
          "EMP-%06d".formatted(i),
          "Nguyễn Văn An " + i,
          i <= 10 ? "IT" : "HR",
          "Developer",
          i == 2 ? "Suspended" : "Active",
          "{\"citizenIdNumber\":\"private-citizen-id\",\"taxCode\":\"private-tax-code\"}");
    }
    long first =
        jdbc.queryForObject(
            "SELECT id FROM employee WHERE employee_code = 'EMP-000001'", Long.class);
    jdbc.update(
        "INSERT INTO employee_contact(employee_id, type, email, phone_number, is_primary) VALUES (?, 'Work', 'work@example.test', '0123456789', TRUE)",
        first);
    jdbc.update(
        "INSERT INTO employee_contact(employee_id, type, email, phone_number, is_primary) VALUES (?, 'Personal', 'private@example.test', 'private-phone', TRUE)",
        first);
    jdbc.update(
        """
        INSERT INTO employee_request(type, state, requester_id, target_name, created_at, last_modified_at)
        VALUES ('Creation', 'PendingApproval', ?, 'Not approved', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        hr.id());
  }

  @Test
  void realTransportNegotiatesAndListsReadOnlyTools() throws Exception {
    var response =
        rpc(
            hr,
            "initialize",
            Map.of(
                "protocolVersion",
                "2025-11-25",
                "capabilities",
                Map.of(),
                "clientInfo",
                Map.of("name", "test-client", "version", "1")));
    assertThat(response.at("/result/serverInfo/name").asText()).isEqualTo("khoa-employees");
    var tools = rpc(hr, "tools/list", Map.of()).at("/result/tools");
    assertThat(tools.size()).isEqualTo(3);
    assertThat(tools.toString()).contains("count_employees", "search_employees", "get_employee");
    for (var tool : tools) assertThat(tool.at("/annotations/readOnlyHint").asBoolean()).isTrue();
  }

  @Test
  void countsLiveApprovedRowsAndSupportsFilters() throws Exception {
    assertThat(call("count_employees", Map.of()).at("/structuredContent/total").asLong())
        .isEqualTo(12);
    assertThat(
            call("count_employees", Map.of("department", "it", "status", "Active"))
                .at("/structuredContent/total")
                .asLong())
        .isEqualTo(9);
    assertThat(
            call("count_employees", Map.of("department", "IT' OR 1=1 --"))
                .at("/structuredContent/total")
                .asLong())
        .isZero();
    jdbc.update("UPDATE employee SET status = 'Terminated' WHERE employee_code = 'EMP-000012'");
    try {
      assertThat(
              call("count_employees", Map.of("status", "Terminated"))
                  .at("/structuredContent/total")
                  .asLong())
          .isEqualTo(1);
    } finally {
      jdbc.update("UPDATE employee SET status = 'Active' WHERE employee_code = 'EMP-000012'");
    }
  }

  @Test
  void searchesAreBoundedAndNeverExposePersonalProfileOrContacts() throws Exception {
    var found = call("search_employees", Map.of("query", "Nguyễn Văn An"));
    assertThat(found.at("/structuredContent/items").size()).isEqualTo(10);
    assertThat(found.at("/structuredContent/total").asLong()).isEqualTo(12);
    assertThat(call("search_employees", Map.of("page", 2)).at("/structuredContent/items").size())
        .isEqualTo(2);
    var employee = call("get_employee", Map.of("employeeCode", "EMP-000001"));
    assertThat(employee.at("/structuredContent/workEmail").asText()).isEqualTo("work@example.test");
    assertThat(employee.toString())
        .doesNotContain("private", "profile_json", "citizenId", "taxCode", "password");
    assertThat(
            call("search_employees", Map.of("query", "%' OR 1=1 --"))
                .at("/structuredContent/total")
                .asLong())
        .isZero();
    assertThat(
            call("search_employees", Map.of("query", "%_")).at("/structuredContent/total").asLong())
        .isZero();
    assertThat(
            call("get_employee", Map.of("employeeCode", "EMP-999999")).get("isError").asBoolean())
        .isTrue();
  }

  @Test
  void surplusLeadingZeroesResolveTheStoredCodeButNeverOverrideAnExactMatch() throws Exception {
    assertThat(
            call("get_employee", Map.of("employeeCode", "EMP-0000001"))
                .at("/structuredContent/employeeCode")
                .asText())
        .isEqualTo("EMP-000001");
    assertThat(
            call("get_employee", Map.of("employeeCode", "EMP-000000000000000001"))
                .at("/structuredContent/employeeCode")
                .asText())
        .isEqualTo("EMP-000001");
    String publicId = UUID.randomUUID().toString();
    try {
      insertEmployee(publicId, "EMP-0000001", "Exact employee code", "Exact code department");
      var exact = call("get_employee", Map.of("employeeCode", "EMP-0000001"));
      assertThat(exact.at("/structuredContent/employeeCode").asText()).isEqualTo("EMP-0000001");
      assertThat(exact.at("/structuredContent/fullName").asText()).isEqualTo("Exact employee code");
    } finally {
      jdbc.update("DELETE FROM employee WHERE public_id = ?", publicId);
    }
  }

  @Test
  void newAndUpdatedEmployeesAreVisibleImmediatelyWithoutAJsonSnapshotOrRestart() throws Exception {
    String publicId = UUID.randomUUID().toString();
    String name = "New employee " + publicId;
    String updatedName = "Updated employee " + publicId;
    String department = "Live lookup " + publicId;
    String code = "EMP-900001";
    assertThat(call("get_employee", Map.of("employeeCode", code)).get("isError").asBoolean())
        .isTrue();
    assertThat(
            call("count_employees", Map.of("department", department))
                .at("/structuredContent/total")
                .asLong())
        .isZero();
    try {
      insertEmployee(publicId, code, name, department);
      assertThat(
              call("count_employees", Map.of("department", department))
                  .at("/structuredContent/total")
                  .asLong())
          .isEqualTo(1);
      assertThat(
              call("search_employees", Map.of("query", name))
                  .at("/structuredContent/items/0/employeeCode")
                  .asText())
          .isEqualTo(code);
      assertThat(
              call("get_employee", Map.of("employeeCode", code))
                  .at("/structuredContent/fullName")
                  .asText())
          .isEqualTo(name);
      assertThat(employeeChat("Thông tin nhân viên EMP-0900001"))
          .contains(name, code, "event:done");

      jdbc.update("UPDATE employee SET full_name = ? WHERE public_id = ?", updatedName, publicId);
      assertThat(
              call("get_employee", Map.of("employeeCode", code))
                  .at("/structuredContent/fullName")
                  .asText())
          .isEqualTo(updatedName);
      assertThat(
              call("search_employees", Map.of("query", name))
                  .at("/structuredContent/total")
                  .asLong())
          .isZero();
      assertThat(employeeChat("Thông tin nhân viên " + code))
          .contains(updatedName)
          .doesNotContain(name);
    } finally {
      jdbc.update("DELETE FROM employee WHERE public_id = ?", publicId);
    }
    assertThat(call("get_employee", Map.of("employeeCode", code)).get("isError").asBoolean())
        .isTrue();
  }

  private void insertEmployee(String publicId, String code, String name, String department) {
    jdbc.update(
        """
        INSERT INTO employee(public_id, employee_code, full_name, department, position,
          status, profile_json, created_at) VALUES (?, ?, ?, ?, 'Developer', 'Active', '{}', CURRENT_TIMESTAMP)
        """,
        publicId,
        code,
        name,
        department);
  }

  private String employeeChat(String question) throws Exception {
    var response =
        post(
            hr,
            "/api/chat/messages",
            json.writeValueAsString(Map.of("topic", "employees", "message", question)),
            true,
            null);
    assertThat(response.statusCode()).isEqualTo(200);
    return response.body();
  }

  @Test
  void rejectsUnauthorizedCallsCsrfBadOriginsAndInvalidArguments() throws Exception {
    var anonymous = new Actor(0, HttpClient.newHttpClient(), new CookieManager());
    assertThat(post(anonymous, EmployeeMcpConfig.ENDPOINT, "{}", false, null).statusCode())
        .isEqualTo(403);
    assertThat(
            anonymous
                .client()
                .send(
                    HttpRequest.newBuilder(uri(EmployeeMcpConfig.ENDPOINT)).GET().build(),
                    HttpResponse.BodyHandlers.ofString())
                .statusCode())
        .isEqualTo(401);
    assertThat(post(student, EmployeeMcpConfig.ENDPOINT, "{}", true, null).statusCode())
        .isEqualTo(403);
    assertThat(post(hr, EmployeeMcpConfig.ENDPOINT, "{}", false, null).statusCode()).isEqualTo(403);
    assertThat(
            post(hr, EmployeeMcpConfig.ENDPOINT, "{}", true, "https://evil.example").statusCode())
        .isEqualTo(403);
    assertThat(
            call("count_employees", Map.of("sql", "DELETE FROM employee"))
                .get("isError")
                .asBoolean())
        .isTrue();
    assertThat(call("count_employees", Map.of("status", "Unknown")).get("isError").asBoolean())
        .isTrue();
    assertThat(call("search_employees", Map.of("page", 0)).get("isError").asBoolean()).isTrue();
    assertThat(call("search_employees", Map.of("page", 1.5)).get("isError").asBoolean()).isTrue();
    assertThat(call("get_employee", Map.of()).get("isError").asBoolean()).isTrue();
  }

  @Test
  void approversAndAdminsCanReadButStudentsCannot() throws Exception {
    for (String role : new String[] {"HR_APPROVER", "ADMIN"}) {
      var actor = actor(role);
      var count =
          rpc(actor, "tools/call", Map.of("name", "count_employees", "arguments", Map.of()));
      assertThat(count.at("/result/structuredContent/total").asLong()).isEqualTo(12);
    }
    var denied =
        post(
            student,
            "/api/chat/messages",
            "{\"topic\":\"employees\",\"message\":\"Tìm nhân viên tên Nguyễn Văn An\"}",
            true,
            null);
    assertThat(denied.statusCode()).isEqualTo(403);
  }

  @Test
  void employeeChatUsesDatabaseToolsWithoutAiOrGroqCredentials() throws Exception {
    var count =
        post(
            hr,
            "/api/chat/messages",
            json.writeValueAsString(
                Map.of(
                    "topic",
                    "employees",
                    "provider",
                    "groq",
                    "message",
                    "Phòng IT có bao nhiêu nhân viên đang làm việc?")),
            true,
            null);
    assertThat(count.statusCode()).isEqualTo(200);
    assertThat(count.body())
        .contains("Có 9 nhân viên", "employee-mcp", "\"answerMode\":\"tool\"", "event:done");
    var info =
        post(
            hr,
            "/api/chat/messages",
            json.writeValueAsString(
                Map.of("topic", "employees", "message", "Thông tin nhân viên EMP-000001")),
            true,
            null);
    assertThat(info.body())
        .contains("Nguyễn Văn An 1", "work@example.test")
        .doesNotContain("private", "citizenId");
    var search =
        post(
            hr,
            "/api/chat/messages",
            json.writeValueAsString(
                Map.of("topic", "employees", "message", "Tìm nhân viên tên Nguyễn Văn An")),
            true,
            null);
    assertThat(search.body()).contains("Tìm thấy 12 nhân viên", "hiển thị 10");
    var denied =
        post(
            student,
            "/api/chat/messages",
            "{\"topic\":\"employees\",\"message\":\"Có bao nhiêu nhân viên?\"}",
            true,
            null);
    assertThat(denied.statusCode()).isEqualTo(403);
    assertThat(denied.body()).doesNotContain("Nguyễn Văn An", "work@example.test");
  }

  private JsonNode call(String name, Map<String, Object> arguments) throws Exception {
    return rpc(hr, "tools/call", Map.of("name", name, "arguments", arguments)).get("result");
  }

  private JsonNode rpc(Actor actor, String method, Map<String, Object> params) throws Exception {
    var response =
        post(
            actor,
            EmployeeMcpConfig.ENDPOINT,
            json.writeValueAsString(
                Map.of("jsonrpc", "2.0", "id", 1, "method", method, "params", params)),
            true,
            null);
    assertThat(response.statusCode()).as(response.body()).isEqualTo(200);
    return json.readTree(response.body());
  }

  private Actor actor(String role) throws Exception {
    String email = UUID.randomUUID() + "@mcp.test";
    var account = auth.register(new RegisterRequest("MCP Test", email, "TestPassword123!"));
    if (role != null)
      jdbc.update("INSERT INTO account_role(user_id, role) VALUES (?, ?)", account.id(), role);
    var cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
    var client = HttpClient.newBuilder().cookieHandler(cookies).build();
    var actor = new Actor(account.id(), client, cookies);
    csrf(actor);
    var login =
        post(
            actor,
            "/api/auth/login",
            json.writeValueAsString(Map.of("email", email, "password", "TestPassword123!")),
            true,
            null);
    assertThat(login.statusCode()).as(login.body()).isEqualTo(200);
    csrf(actor);
    return actor;
  }

  private void csrf(Actor actor) throws Exception {
    actor
        .client()
        .send(
            HttpRequest.newBuilder(uri("/api/auth/csrf")).GET().build(),
            HttpResponse.BodyHandlers.ofString());
  }

  private HttpResponse<String> post(
      Actor actor, String path, String body, boolean csrf, String origin) throws Exception {
    var request =
        HttpRequest.newBuilder(uri(path))
            .timeout(Duration.ofSeconds(15))
            .header("Content-Type", "application/json")
            .header("Accept", "application/json, text/event-stream");
    if (csrf)
      actor.cookies().getCookieStore().getCookies().stream()
          .filter(cookie -> "XSRF-TOKEN".equals(cookie.getName()))
          .findFirst()
          .ifPresent(cookie -> request.header("X-XSRF-TOKEN", cookie.getValue()));
    if (origin != null) request.header("Origin", origin);
    return actor
        .client()
        .send(
            request.POST(HttpRequest.BodyPublishers.ofString(body)).build(),
            HttpResponse.BodyHandlers.ofString());
  }

  private URI uri(String path) {
    return URI.create("http://localhost:" + port + path);
  }

  private record Actor(long id, HttpClient client, CookieManager cookies) {}
}
