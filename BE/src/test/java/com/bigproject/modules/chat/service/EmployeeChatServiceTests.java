package com.bigproject.modules.chat.service;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class EmployeeChatServiceTests {
  @ParameterizedTest
  @ValueSource(
      strings = {
        "Có bao nhiêu nhân viên?",
        "Số nhân viên trong database",
        "Tổng số nhân viên là bao nhiêu?",
        "Đếm số nhân viên"
      })
  void recognizesCounts(String question) {
    assertThat(EmployeeChatService.plan(question).tool()).isEqualTo("count_employees");
  }

  @Test
  void retainsFiltersAndVietnameseNames() {
    var count = EmployeeChatService.plan("Phòng IT có bao nhiêu nhân viên đang làm việc?");
    assertThat(count.arguments())
        .containsExactlyInAnyOrderEntriesOf(Map.of("department", "IT", "status", "Active"));
    var name = EmployeeChatService.plan("Tìm nhân viên tên Nguyễn Văn An");
    assertThat(name.tool()).isEqualTo("search_employees");
    assertThat(name.arguments()).containsEntry("query", "Nguyễn Văn An");
    assertThat(EmployeeChatService.plan("Thông tin nhân viên EMP-000001").arguments())
        .containsEntry("employeeCode", "EMP-000001");
  }

  @Test
  void passesZeroPaddedCodesToTheLiveLookupTool() {
    var plan = EmployeeChatService.plan("Thông tin nhân viên EMP-0000050");
    assertThat(plan.tool()).isEqualTo("get_employee");
    assertThat(plan.arguments())
        .containsExactlyInAnyOrderEntriesOf(Map.of("employeeCode", "EMP-0000050"));
  }

  @ParameterizedTest
  @ValueSource(
      strings = {
        "Có bao nhiêu nhân viên nữ?",
        "Có bao nhiêu nhân viên trên 30 tuổi?",
        "Lương của nhân viên",
        "Xóa tất cả nhân viên",
        "Có bao nhiêu nhân viên đang làm việc đã nghỉ việc?"
      })
  void unsupportedFiltersNeverBecomeAnUnfilteredCount(String question) {
    assertThat(EmployeeChatService.plan(question)).isNull();
  }
}
