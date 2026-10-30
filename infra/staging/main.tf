data "azurerm_client_config" "current" {}

locals {
  resource_group_name    = "rg-abc-prediction-staging"
  container_app_name     = "abc-prediction-staging"
  container_job_name     = "abc-prediction-agent"
  storage_account_name   = "stabcpred${var.name_suffix}"
  acr_name               = "abcpred${var.name_suffix}"
  openai_account_name    = "oai-abc-prediction-${var.name_suffix}"
  openai_deployment_name = "agent"
  key_vault_name         = "kvabcpred${var.name_suffix}"
}

resource "azurerm_resource_group" "staging" {
  name     = local.resource_group_name
  location = var.location
}

resource "azurerm_log_analytics_workspace" "staging" {
  name                = "log-abc-prediction-${var.name_suffix}"
  location            = azurerm_resource_group.staging.location
  resource_group_name = azurerm_resource_group.staging.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_registry" "staging" {
  name                = local.acr_name
  resource_group_name = azurerm_resource_group.staging.name
  location            = azurerm_resource_group.staging.location
  sku                 = "Basic"
}

resource "azurerm_container_app_environment" "staging" {
  name                       = "cae-abc-prediction-staging"
  location                   = azurerm_resource_group.staging.location
  resource_group_name        = azurerm_resource_group.staging.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.staging.id
}

# The registry block accepts a user-assigned identity. A system-assigned
# identity cannot be selected there.
resource "azurerm_user_assigned_identity" "app" {
  name                = "id-abc-prediction-staging-app"
  location            = azurerm_resource_group.staging.location
  resource_group_name = azurerm_resource_group.staging.name
}

resource "azurerm_role_assignment" "app_acr_pull" {
  scope                = azurerm_container_registry.staging.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_user_assigned_identity" "github" {
  name                = "id-abc-prediction-staging-github"
  location            = azurerm_resource_group.staging.location
  resource_group_name = azurerm_resource_group.staging.name
}

resource "azurerm_federated_identity_credential" "github_main" {
  name                      = "github-main"
  user_assigned_identity_id = azurerm_user_assigned_identity.github.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "repo:alexpberger@37416787/abc-prediction-platform@1411960546:ref:refs/heads/main"
}

resource "azurerm_role_assignment" "github_acr_push" {
  scope                = azurerm_container_registry.staging.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
}

resource "azurerm_role_assignment" "github_container_apps" {
  scope                = azurerm_resource_group.staging.id
  role_definition_name = "Container Apps Contributor"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
}

# Container Apps Contributor does not include jobs. Without this role the
# deploy identity receives "does not exist" when it updates the agent job.
resource "azurerm_role_assignment" "github_container_app_jobs" {
  scope                = azurerm_resource_group.staging.id
  role_definition_name = "Container Apps Jobs Contributor"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
}

# Updating the job sends its identities back. That requires permission to assign them.
resource "azurerm_role_assignment" "github_managed_identity_operator" {
  scope                = azurerm_resource_group.staging.id
  role_definition_name = "Managed Identity Operator"
  principal_id         = azurerm_user_assigned_identity.github.principal_id
}

resource "azurerm_container_app" "staging" {
  count                        = var.container_image == null ? 0 : 1
  name                         = local.container_app_name
  resource_group_name          = azurerm_resource_group.staging.name
  container_app_environment_id = azurerm_container_app_environment.staging.id
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.staging.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 1

    container {
      name   = "app"
      image  = coalesce(var.container_image, "unused")
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "PROPOSALS_PATH"
        value = "/data/proposals.json"
      }

      env {
        name  = "MARKET_CATALOG_PATH"
        value = "/data/market-catalog.json"
      }

      volume_mounts {
        name = "proposals"
        path = "/data"
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/api/health"
      }
    }

    volume {
      name         = "proposals"
      storage_name = azurerm_container_app_environment_storage.proposals.name
      storage_type = "AzureFile"
    }
  }

  depends_on = [azurerm_role_assignment.app_acr_pull]

  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
    ]
  }
}

# The public app reads proposals from the share and has no model settings.
# Only the job identity can call the model.
resource "azurerm_cognitive_account" "openai" {
  name                          = local.openai_account_name
  location                      = var.openai_location
  resource_group_name           = azurerm_resource_group.staging.name
  kind                          = "OpenAI"
  sku_name                      = "S0"
  custom_subdomain_name         = local.openai_account_name
  local_auth_enabled            = false
  public_network_access_enabled = true
}

resource "azurerm_cognitive_deployment" "agent" {
  name                 = local.openai_deployment_name
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.openai_model_name
    version = var.openai_model_version
  }

  sku {
    name     = "DataZoneStandard"
    capacity = var.openai_deployment_capacity
  }

  version_upgrade_option = "NoAutoUpgrade"
}

resource "azurerm_role_assignment" "caller_openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_key_vault" "staging" {
  name                       = local.key_vault_name
  location                   = azurerm_resource_group.staging.location
  resource_group_name        = azurerm_resource_group.staging.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = false
  soft_delete_retention_days = 7
}

resource "azurerm_role_assignment" "caller_key_vault_secrets_officer" {
  scope                = azurerm_key_vault.staging.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_key_vault_secret" "openai_endpoint" {
  name         = "openai-endpoint"
  value        = azurerm_cognitive_account.openai.endpoint
  key_vault_id = azurerm_key_vault.staging.id

  depends_on = [azurerm_role_assignment.caller_key_vault_secrets_officer]
}

resource "azurerm_key_vault_secret" "openai_deployment" {
  name         = "openai-deployment"
  value        = azurerm_cognitive_deployment.agent.name
  key_vault_id = azurerm_key_vault.staging.id

  depends_on = [azurerm_role_assignment.caller_key_vault_secrets_officer]
}

resource "azurerm_storage_account" "proposals" {
  name                     = local.storage_account_name
  resource_group_name      = azurerm_resource_group.staging.name
  location                 = azurerm_resource_group.staging.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

resource "azurerm_storage_share" "proposals" {
  name               = "proposals"
  storage_account_id = azurerm_storage_account.proposals.id
  quota              = 1
}

resource "azurerm_container_app_environment_storage" "proposals" {
  name                         = "proposals"
  container_app_environment_id = azurerm_container_app_environment.staging.id
  account_name                 = azurerm_storage_account.proposals.name
  share_name                   = azurerm_storage_share.proposals.name
  access_key                   = azurerm_storage_account.proposals.primary_access_key
  access_mode                  = "ReadWrite"
}

resource "azurerm_user_assigned_identity" "agent" {
  name                = "id-abc-prediction-staging-agent"
  location            = azurerm_resource_group.staging.location
  resource_group_name = azurerm_resource_group.staging.name
}

resource "azurerm_role_assignment" "agent_openai_user" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.agent.principal_id
}

resource "azurerm_role_assignment" "agent_key_vault_secrets_user" {
  scope                = azurerm_key_vault.staging.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.agent.principal_id
}

resource "azurerm_container_app_job" "agent" {
  count                        = var.container_image == null ? 0 : 1
  name                         = local.container_job_name
  location                     = azurerm_resource_group.staging.location
  resource_group_name          = azurerm_resource_group.staging.name
  container_app_environment_id = azurerm_container_app_environment.staging.id
  replica_timeout_in_seconds   = 600
  replica_retry_limit          = 0

  identity {
    type = "UserAssigned"
    identity_ids = [
      azurerm_user_assigned_identity.app.id,
      azurerm_user_assigned_identity.agent.id,
    ]
  }

  registry {
    server   = azurerm_container_registry.staging.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  secret {
    name                = "openai-endpoint"
    identity            = azurerm_user_assigned_identity.agent.id
    key_vault_secret_id = azurerm_key_vault_secret.openai_endpoint.versionless_id
  }

  secret {
    name                = "openai-deployment"
    identity            = azurerm_user_assigned_identity.agent.id
    key_vault_secret_id = azurerm_key_vault_secret.openai_deployment.versionless_id
  }

  schedule_trigger_config {
    cron_expression          = "0 10,22 * * *"
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = "agent"
      image   = coalesce(var.container_image, "unused")
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "app.daily"]

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.agent.client_id
      }

      env {
        name  = "PROPOSALS_PATH"
        value = "/data/proposals.json"
      }

      env {
        name  = "MARKET_CATALOG_PATH"
        value = "/data/market-catalog.json"
      }

      env {
        name        = "AZURE_OPENAI_ENDPOINT"
        secret_name = "openai-endpoint"
      }

      env {
        name        = "AZURE_OPENAI_CHAT_MODEL"
        secret_name = "openai-deployment"
      }

      volume_mounts {
        name = "proposals"
        path = "/data"
      }
    }

    volume {
      name         = "proposals"
      storage_name = azurerm_container_app_environment_storage.proposals.name
      storage_type = "AzureFile"
    }
  }

  depends_on = [
    azurerm_role_assignment.app_acr_pull,
    azurerm_role_assignment.agent_openai_user,
    azurerm_role_assignment.agent_key_vault_secrets_user,
  ]

  # The image is published by the deploy workflow. Secret is a set, so an
  # apply can restore a Key Vault binding that a deploy command replaced.
  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
    ]
  }
}
