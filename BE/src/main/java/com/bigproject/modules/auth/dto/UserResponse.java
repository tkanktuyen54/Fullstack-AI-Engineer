package com.bigproject.modules.auth.dto;

import com.bigproject.modules.user.entity.Account;
import java.util.List;

public record UserResponse(long id, String name, String email, List<String> roles) {
  public static UserResponse from(Account account, List<String> roles) {
    return new UserResponse(
        account.id(),
        (account.firstName() + " " + account.lastName()).trim(),
        account.email(),
        roles);
  }
}
