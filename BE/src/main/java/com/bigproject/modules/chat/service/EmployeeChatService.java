package com.bigproject.modules.chat.service;

import com.bigproject.modules.employee.mcp.EmployeeTools;
import java.text.Normalizer;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.stereotype.Service;

/** Deterministic tool routing: counts and employee fields are never invented by a model. */
@Service
public class EmployeeChatService {
  private static final String HELP =
      "Bạn có thể hỏi: “Có bao nhiêu nhân viên?”, "
          + "“Có bao nhiêu nhân viên đang làm việc?”, “Phòng IT có bao nhiêu nhân viên?”, "
          + "“Thông tin nhân viên EMP-000001” hoặc “Tìm nhân viên tên Nguyễn Văn An”. "
          + "Hiện hỗ trợ lọc theo phòng ban và trạng thái; chỉ tra cứu hồ sơ đã được duyệt.";
  private static final Pattern DEPARTMENT =
      Pattern.compile(
          "\\bphong(?: ban)?\\s+(?:\"([^\"]+)\"|'([^']+)'|(.+?)(?=\\s+(?:co|dang|da|tam|bao nhieu|gom|la)\\b|[?.!]|$))");
  private static final Pattern NAME =
      Pattern.compile(
          "^(?:tim(?: kiem)?|tra cuu|thong tin(?: cua)?|xem(?: thong tin)?)(?: nhan vien)?(?: ten(?: la)?)?\\s+(.+)$");
  private static final Pattern COUNT =
      Pattern.compile(
          "^(?:hien tai )?(?:(?:cong ty|database|db|he thong) )?(?:co )?"
              + "(?:bao nhieu|tong so|so(?: luong)?|dem(?: so)?) nhan vien"
              + "(?: (?:hien tai|trong database|trong db|trong he thong|la bao nhieu|la gi))?$");
  private final EmployeeTools tools;

  public EmployeeChatService(EmployeeTools tools) {
    this.tools = tools;
  }

  public ChatService.Reply answer(String message, boolean authorized) {
    EmployeeTools.requireAccess(authorized);
    Plan plan = plan(message);
    if (plan == null) return reply(HELP, "not_found");
    Object result = tools.call(plan.tool(), plan.arguments(), authorized);
    String text;
    if (result instanceof EmployeeTools.Count count) {
      String scope =
          count.department().isBlank() ? "" : " tại phòng ban “" + count.department() + "”";
      String status =
          count.status().isBlank() ? "" : " có trạng thái “" + status(count.status()) + "”";
      text =
          "Có "
              + count.total()
              + " nhân viên"
              + scope
              + status
              + " trong database (hồ sơ đã được duyệt).";
    } else if (result instanceof EmployeeTools.EmployeeInfo employee) {
      text = format(employee);
    } else {
      var search = (EmployeeTools.Search) result;
      if (search.total() == 0) {
        text =
            "Không tìm thấy nhân viên phù hợp trong database. Hãy kiểm tra tên hoặc mã nhân viên.";
      } else {
        text =
            "Tìm thấy "
                + search.total()
                + " nhân viên; hiển thị "
                + search.items().size()
                + " kết quả đầu tiên.\n\n"
                + String.join(
                    "\n\n", search.items().stream().map(EmployeeChatService::format).toList());
        if (search.total() > search.items().size())
          text += "\n\nHãy nhập tên hoặc mã cụ thể hơn để thu hẹp kết quả.";
      }
    }
    return reply(text, "tool");
  }

  static Plan plan(String message) {
    // NFC preserves offsets when folding Vietnamese characters for command recognition.
    String original =
        Normalizer.normalize(message, Normalizer.Form.NFC)
            .strip()
            .replaceAll("[?!.]+$", "")
            .strip();
    String folded = fold(original);
    var code = Pattern.compile("\\bemp-[0-9]{6,18}\\b").matcher(folded);
    if (code.find() && (folded.equals(code.group()) || NAME.matcher(folded).matches())) {
      return new Plan(
          "get_employee", Map.of("employeeCode", code.group().toUpperCase(Locale.ROOT)));
    }
    var args = new HashMap<String, Object>();
    var department = DEPARTMENT.matcher(folded);
    if (department.find()) {
      int group = department.group(1) != null ? 1 : department.group(2) != null ? 2 : 3;
      args.put(
          "department", original.substring(department.start(group), department.end(group)).strip());
      original = original.substring(0, department.start()) + original.substring(department.end());
      folded = fold(original);
    }
    String[][] statuses = {
      {"dang lam viec|dang hoat dong|active", "Active"},
      {"tam dinh chi|bi dinh chi|dinh chi|suspended", "Suspended"},
      {"da nghi viec|nghi viec|da cham dut|terminated", "Terminated"}
    };
    // Filters are removed only for count/list commands, never from a person's name.
    String command = folded;
    for (var entry : statuses) {
      var status = Pattern.compile("\\b(?:" + entry[0] + ")\\b").matcher(command);
      if (status.find()) {
        if (args.containsKey("status")) return null;
        args.put("status", entry[1]);
        command = status.replaceAll(" ");
      }
    }
    command =
        command
            .replaceAll("\\s+", " ")
            .strip()
            .replaceFirst("^(?:vui long|cho toi biet|cho toi|hay) ", "");
    if (COUNT.matcher(command).matches()) return new Plan("count_employees", args);
    if (command.equals("danh sach nhan vien")) return new Plan("search_employees", args);
    // Name lookup is deliberately explicit so unsupported questions cannot become a total count.
    var name = NAME.matcher(folded);
    if (name.matches()) {
      String query =
          original.substring(name.start(1), name.end(1)).strip().replaceAll("^[\"']|[\"']$", "");
      if (query.length() < 2 || query.length() > 200 || fold(query).equals("nhan vien"))
        return null;
      args.remove("status");
      args.put("query", query);
      return new Plan("search_employees", args);
    }
    return null;
  }

  private static String fold(String value) {
    return Normalizer.normalize(value, Normalizer.Form.NFD)
        .replaceAll("\\p{M}", "")
        .replace('đ', 'd')
        .replace('Đ', 'D')
        .toLowerCase(Locale.ROOT);
  }

  private static String format(EmployeeTools.EmployeeInfo e) {
    return e.employeeCode()
        + " — "
        + e.fullName()
        + "\nPhòng ban: "
        + e.department()
        + "\nChức vụ: "
        + e.position()
        + "\nTrạng thái: "
        + status(e.status())
        + "\nEmail công việc: "
        + value(e.workEmail())
        + "\nĐiện thoại công việc: "
        + value(e.workPhone());
  }

  private static String status(String value) {
    return switch (value) {
      case "Active" -> "Đang làm việc";
      case "Suspended" -> "Tạm đình chỉ";
      case "Terminated" -> "Đã nghỉ việc";
      default -> value;
    };
  }

  private static String value(String value) {
    return value == null || value.isBlank() ? "Chưa có dữ liệu" : value;
  }

  private static ChatService.Reply reply(String message, String mode) {
    return new ChatService.Reply(
        message, "employees", List.of(), List.of(), "employee-mcp", mode, "");
  }

  record Plan(String tool, Map<String, Object> arguments) {}
}
