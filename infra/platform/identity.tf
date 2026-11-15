# Cognito is the identity provider. Groups are the RBAC roles; they arrive in the token as
# cognito:groups and every app checks them. In a real enterprise this pool federates to the
# company IdP (Entra ID / Okta over SAML or OIDC): one aws_cognito_identity_provider resource,
# which needs the customer's metadata, so it is not configured here.
resource "aws_cognito_user_pool" "this" {
  name                     = local.name
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = "OPTIONAL"
  deletion_protection      = var.env == "prod" ? "ACTIVE" : "INACTIVE"

  software_token_mfa_configuration {
    enabled = true
  }

  admin_create_user_config {
    allow_admin_create_user_only = true # no self sign-up: an admin invites every user
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 3
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_group" "role" {
  for_each     = var.roles
  user_pool_id = aws_cognito_user_pool.this.id
  name         = each.key
  description  = each.value
}

# Public client for the approver CLI and tests (no secret; SRP or password auth).
resource "aws_cognito_user_pool_client" "cli" {
  name                          = "${local.name}-cli"
  user_pool_id                  = aws_cognito_user_pool.this.id
  generate_secret               = false
  prevent_user_existence_errors = "ENABLED"
  explicit_auth_flows           = ["ALLOW_USER_SRP_AUTH", "ALLOW_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  access_token_validity         = 60
  id_token_validity             = 60
  refresh_token_validity        = 1
  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}
