package com.customer.can.userauth.api;

import com.customer.can.userauth.application.B2bInvitationService;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/users")
public class UserController {

    private final B2bInvitationService invitations;

    public UserController(B2bInvitationService invitations) {
        this.invitations = invitations;
    }

    public record InviteRequest(@Email @NotBlank String email, @NotBlank String displayName) {}

    /**
     * Invites an external user (B2B guest). Requires the {@code users.invite}
     * scope - typically held by internal admins.
     */
    @PostMapping("/invite")
    @PreAuthorize("hasAuthority('SCOPE_users.invite')")
    public ResponseEntity<String> invite(@RequestBody InviteRequest body) {
        String id = invitations.invite(body.email(), body.displayName(), true);
        return id == null
                ? ResponseEntity.internalServerError().build()
                : ResponseEntity.accepted().body(id);
    }
}
