package com.bigproject.modules.employee.mcp;

import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

/** Read-only, bounded employee tools shared by MCP clients and the chat UI. */
@Service
@Transactional(readOnly = true)
public class EmployeeTools {
  private static final Set<String> ROLES = Set.of("ROLE_HR", "ROLE_HR_APPROVER", "ROLE_ADMIN");
  private static final String FILTER =
      " WHERE (? = '' OR e.status = ?) AND (? = '' OR LOWER(e.department) = LOWER(?))";
  private static final String COLUMNS =
      """
      SELECT e.employee_code, e.full_name, e.department, e.position, e.status,
        (SELECT c.email FROM employee_contact c WHERE c.employee_id = e.id
          AND c.type = 'Work' AND c.is_primary = TRUE ORDER BY c.id LIMIT 1) AS work_email,
        (SELECT c.phone_number FROM employee_contact c WHERE c.employee_id = e.id
          AND c.type = 'Work' AND c.is_primary = TRUE ORDER BY c.id LIMIT 1) AS work_phone
      FROM employee e
      """;
  private final JdbcTemplate jdbc;

  public EmployeeTools(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  public static boolean authorized(Authentication authentication) {
    return authentication != null
        && authentication.isAuthenticated()
        && authentication.getAuthorities().stream().anyMatch(a -> ROLES.contains(a.getAuthority()));
  }

  public static void requireAccess(boolean authorized) {
    if (!authorized) {
      throw new ResponseStatusException(
          HttpStatus.FORBIDDEN, "Tra cứu nhân sự yêu cầu tài khoản HR, HR_APPROVER hoặc ADMIN.");
    }
  }

  public Object call(String name, Map<String, Object> arguments, boolean authorized) {
    requireAccess(authorized);
    Map<String, Object> args = arguments == null ? Map.of() : arguments;
    Set<String> allowed =
        switch (name) {
          case "count_employees" -> Set.of("status", "department");
          case "search_employees" -> Set.of("query", "status", "department", "page");
          case "get_employee" -> Set.of("employeeCode");
          default -> throw invalid("Tool nhân sự không tồn tại.");
        };
    if (!allowed.containsAll(args.keySet())) throw invalid("Tham số tra cứu không hợp lệ.");
    if ("get_employee".equals(name)) {
      String code = text(args, "employeeCode", 40).toUpperCase(java.util.Locale.ROOT);
      if (!code.matches("EMP-[0-9]{6,18}")) throw invalid("Mã nhân viên có dạng EMP-000001.");
      return read(COLUMNS + " WHERE e.employee_code = ?", code).stream()
          .findFirst()
          .orElseThrow(
              () ->
                  new ResponseStatusException(
                      HttpStatus.NOT_FOUND, "Không tìm thấy nhân viên " + code + "."));
    }
    String status = text(args, "status", 30);
    String department = text(args, "department", 200);
    if (!Set.of("", "Active", "Suspended", "Terminated").contains(status)) {
      throw invalid("Trạng thái phải là Active, Suspended hoặc Terminated.");
    }
    if ("count_employees".equals(name)) {
      long total =
          jdbc.queryForObject(
              "SELECT COUNT(*) FROM employee e" + FILTER,
              Long.class,
              status,
              status,
              department,
              department);
      return new Count(total, status, department);
    }
    String query = text(args, "query", 200);
    if (query.length() == 1) throw invalid("Nhập ít nhất 2 ký tự để tìm nhân viên.");
    int page = 1;
    if (args.containsKey("page")) {
      Object value = args.get("page");
      if (!(value instanceof Number number)
          || number.doubleValue() != number.intValue()
          || number.intValue() < 1
          || number.intValue() > 1000) {
        throw invalid("Trang phải là số nguyên từ 1 đến 1000.");
      }
      page = ((Number) value).intValue();
    }
    String search =
        "%"
            + query
                .toLowerCase(java.util.Locale.ROOT)
                .replace("!", "!!")
                .replace("%", "!%")
                .replace("_", "!_")
            + "%";
    String filter =
        FILTER
            + " AND (LOWER(e.full_name) LIKE ? ESCAPE '!' OR LOWER(e.employee_code) LIKE ? ESCAPE '!')";
    long total =
        jdbc.queryForObject(
            "SELECT COUNT(*) FROM employee e" + filter,
            Long.class,
            status,
            status,
            department,
            department,
            search,
            search);
    var items =
        read(
            COLUMNS + filter + " ORDER BY e.employee_code, e.id LIMIT 10 OFFSET ?",
            status,
            status,
            department,
            department,
            search,
            search,
            (page - 1) * 10);
    return new Search(total, page, 10, items);
  }

  private List<EmployeeInfo> read(String sql, Object... args) {
    return jdbc.query(
        sql,
        (rs, row) ->
            new EmployeeInfo(
                rs.getString("employee_code"),
                rs.getString("full_name"),
                rs.getString("department"),
                rs.getString("position"),
                rs.getString("status"),
                rs.getString("work_email"),
                rs.getString("work_phone")),
        args);
  }

  private static String text(Map<String, Object> args, String name, int limit) {
    Object value = args.getOrDefault(name, "");
    if (!(value instanceof String text) || text.length() > limit) {
      throw invalid("Tham số " + name + " không hợp lệ.");
    }
    return text.strip();
  }

  private static ResponseStatusException invalid(String message) {
    return new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
  }

  public record Count(long total, String status, String department) {}

  public record Search(long total, int page, int pageSize, List<EmployeeInfo> items) {}

  public record EmployeeInfo(
      String employeeCode,
      String fullName,
      String department,
      String position,
      String status,
      String workEmail,
      String workPhone) {}
}
