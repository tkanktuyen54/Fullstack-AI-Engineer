package com.bigproject.modules.home.controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class HomeController {

  @GetMapping("/")
  public String hello() {
    return "Tuyen Pham - Tư vấn khóa học API — /swagger-ui.html";
  }
}
