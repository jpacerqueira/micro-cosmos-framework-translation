package com.customer.can.userauth.application;

import com.azure.identity.DefaultAzureCredentialBuilder;
import com.microsoft.graph.authentication.TokenCredentialAuthProvider;
import com.microsoft.graph.models.Invitation;
import com.microsoft.graph.requests.GraphServiceClient;
import okhttp3.Request;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * Wraps the Microsoft Graph "invitations" API for the SAD's B2B flow:
 * an internal admin invites an external user; Azure AD sends an email; the
 * external user accepts and becomes a Guest user in our tenant; the BFF
 * then assigns them an application role.
 *
 * <p>Auth uses workload identity ({@code DefaultAzureCredential}) so no
 * client secret lives in the cluster.
 */
@Service
public class B2bInvitationService {

    private static final Logger log = LoggerFactory.getLogger(B2bInvitationService.class);

    private final GraphServiceClient<Request> graph;
    private final String defaultRedirectUrl;

    public B2bInvitationService(@Value("${app.b2b.redirect-url}") String redirect) {
        var cred = new DefaultAzureCredentialBuilder().build();
        var auth = new TokenCredentialAuthProvider(List.of("https://graph.microsoft.com/.default"), cred);
        this.graph = GraphServiceClient.builder().authenticationProvider(auth).buildClient();
        this.defaultRedirectUrl = redirect;
    }

    /**
     * Invites an external user. Caller is responsible for ensuring the
     * inviter is authorised.
     *
     * @return the Graph object id of the created invitation, or null on failure.
     */
    public String invite(String externalEmail, String displayName, boolean sendMessage) {
        try {
            var inv = new Invitation();
            inv.invitedUserEmailAddress = externalEmail;
            inv.invitedUserDisplayName  = displayName;
            inv.inviteRedirectUrl       = defaultRedirectUrl;
            inv.sendInvitationMessage   = sendMessage;

            var created = graph.invitations().buildRequest().post(inv);
            log.info("B2B invitation sent email={} id={}", maskEmail(externalEmail), created.id);
            return created.id;
        } catch (Exception e) {
            log.error("Failed to send B2B invitation to {}", maskEmail(externalEmail), e);
            return null;
        }
    }

    /** Redacts an email address for logging — the Graph invitation id already
     * provides a non-PII correlation key; the raw address is not needed in
     * application logs, which typically have looser access control and longer
     * retention than the identity system itself. */
    private static String maskEmail(String email) {
        if (email == null || email.isBlank()) {
            return "(none)";
        }
        int at = email.indexOf('@');
        if (at <= 1) {
            return "***" + email.substring(Math.max(at, 0));
        }
        return email.charAt(0) + "***" + email.substring(at);
    }
}
