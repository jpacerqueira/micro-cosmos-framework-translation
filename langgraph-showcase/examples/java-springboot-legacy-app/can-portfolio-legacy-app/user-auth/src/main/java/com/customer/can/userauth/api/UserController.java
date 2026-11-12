package com.customer.can.userauth.api;

import com.customer.can.userauth.domain.AppUser;
import com.customer.can.userauth.service.UserService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/v1/users")
@Api(tags = "User Management")
public class UserController {
    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    @GetMapping
    @ApiOperation("List all users")
    public ResponseEntity<List<AppUser>> listUsers() {
        return ResponseEntity.ok(userService.findAll());
    }

    @GetMapping("/{id}")
    @ApiOperation("Get user by ID")
    public ResponseEntity<AppUser> getUser(@PathVariable String id) {
        return userService.findById(id)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @PostMapping
    @ApiOperation("Create a new user")
    public ResponseEntity<AppUser> createUser(@RequestBody AppUser user) {
        return ResponseEntity.status(201).body(userService.create(user));
    }
}
