###############################################################################
# Azure AD application + service principal for the WebApp/API. B2B/B2C
# integration is configured at tenant level - this module registers the app
# and exposes the client_id used by the Spring Boot OAuth2 resource server.
###############################################################################

variable "display_name"    { type = string }
variable "redirect_uris"   { type = list(string) }
variable "identifier_uris" { type = list(string) }
variable "tenant_id"       { type = string }
variable "reply_homepage"  { type = string }

resource "azuread_application" "this" {
  display_name     = var.display_name
  identifier_uris  = var.identifier_uris
  sign_in_audience = "AzureADMyOrg"

  web {
    homepage_url  = var.reply_homepage
    redirect_uris = var.redirect_uris
    implicit_grant {
      access_token_issuance_enabled = false
      id_token_issuance_enabled     = true
    }
  }

  api {
    requested_access_token_version = 2
  }

  required_resource_access {
    resource_app_id = "00000003-0000-0000-c000-000000000000" # Microsoft Graph
    resource_access {
      id   = "e1fe6dd8-ba31-4d61-89e7-88639da4683d" # User.Read
      type = "Scope"
    }
  }
}

resource "azuread_service_principal" "this" {
  client_id = azuread_application.this.client_id
}

output "client_id"          { value = azuread_application.this.client_id }
output "service_principal_id" { value = azuread_service_principal.this.id }
