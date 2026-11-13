package com.bigproject.modules.chat.controller;

import com.bigproject.modules.chat.dto.ModelConfigRequest;
import com.bigproject.modules.chat.service.ModelConfigService;
import jakarta.servlet.http.HttpSession;
import jakarta.validation.Valid;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/chat/config")
public class ModelConfigController {
  private final ModelConfigService config;

  public ModelConfigController(ModelConfigService config) {
    this.config = config;
  }

  @GetMapping
  public ResponseEntity<ModelConfigService.View> read(HttpSession session) {
    return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(config.read(session));
  }

  @PutMapping
  public ResponseEntity<ModelConfigService.View> save(
      @Valid @RequestBody ModelConfigRequest request, HttpSession session) {
    return ResponseEntity.ok()
        .cacheControl(CacheControl.noStore())
        .body(config.save(session, request));
  }
}
