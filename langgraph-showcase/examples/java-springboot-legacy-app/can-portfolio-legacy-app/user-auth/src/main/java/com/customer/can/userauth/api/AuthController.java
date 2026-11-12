package com.customer.can.userauth.api;

import com.customer.can.userauth.domain.AppUser;
import com.customer.can.userauth.service.JwtService;
import com.customer.can.userauth.service.UserService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.apache.logging.log4j.ThreadContext;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/v1/auth")
@Api(tags = "Authentication")
public class AuthController {
    private static final Logger log = LogManager.getLogger(AuthController.class);

    private final UserService userService;
    private final JwtService jwtService;

    public AuthController(UserService userService, JwtService jwtService) {
        this.userService = userService;
        this.jwtService = jwtService;
    }

    @PostMapping("/login")
    @ApiOperation("Authenticate user and return JWT token")
    public ResponseEntity<Map<String, String>> login(@RequestBody Map<String, String> credentials) {
        String email = credentials.get("email");
        String password = credentials.get("password");
        log.info("action=login_attempt email={} correlationId={}", email, ThreadContext.get("correlationId"));

        if (!userService.authenticate(email, password)) {
            log.warn("action=login_failed email={}", email);
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        }

        AppUser user = userService.findByEmail(email).orElseThrow();
        String token = jwtService.generateToken(user.getId(), user.getEmail(), user.getRole(), user.getCompanyId());
        String refreshToken = jwtService.generateRefreshToken(user.getEmail());
        userService.recordLogin(email);

        Map<String, String> response = new HashMap<>();
        response.put("accessToken", token);
        response.put("refreshToken", refreshToken);
        response.put("userId", user.getId());
        response.put("email", user.getEmail());
        response.put("role", user.getRole());
        response.put("fullName", user.getFullName());

        log.info("action=login_success email={} role={}", email, user.getRole());
        return ResponseEntity.ok(response);
    }

    @PostMapping("/refresh")
    @ApiOperation("Refresh access token")
    public ResponseEntity<Map<String, String>> refresh(@RequestBody Map<String, String> body) {
        String refreshToken = body.get("refreshToken");
        if (!jwtService.isTokenValid(refreshToken)) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        }
        String email = jwtService.getEmailFromToken(refreshToken);
        AppUser user = userService.findByEmail(email)
                .orElseThrow(() -> new RuntimeException("User not found"));
        String newToken = jwtService.generateToken(user.getId(), user.getEmail(), user.getRole(), user.getCompanyId());
        Map<String, String> response = new HashMap<>();
        response.put("accessToken", newToken);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/validate")
    @ApiOperation("Validate a JWT token")
    public ResponseEntity<Map<String, Object>> validate(@RequestParam String token) {
        if (!jwtService.isTokenValid(token)) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        }
        io.jsonwebtoken.Claims claims = jwtService.validateToken(token);
        Map<String, Object> result = new HashMap<>();
        result.put("valid", true);
        result.put("userId", claims.get("userId"));
        result.put("email", claims.getSubject());
        result.put("role", claims.get("role"));
        result.put("companyId", claims.get("companyId"));
        return ResponseEntity.ok(result);
    }
}
