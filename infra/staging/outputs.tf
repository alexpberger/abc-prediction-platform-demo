output "resource_group_name" {
  value = azurerm_resource_group.staging.name
}

output "acr_name" {
  value = azurerm_container_registry.staging.name
}

output "acr_login_server" {
  value = azurerm_container_registry.staging.login_server
}

output "container_app_name" {
  value = local.container_app_name
}

output "container_job_name" {
  value = local.container_job_name
}

output "staging_url" {
  value = length(azurerm_container_app.staging) == 0 ? null : "https://${azurerm_container_app.staging[0].ingress[0].fqdn}"
}

output "azure_client_id" {
  value = azurerm_user_assigned_identity.github.client_id
}

output "azure_tenant_id" {
  value = data.azurerm_client_config.current.tenant_id
}

output "azure_subscription_id" {
  value = data.azurerm_client_config.current.subscription_id
}

output "openai_account_name" {
  value = azurerm_cognitive_account.openai.name
}

output "openai_endpoint" {
  value = azurerm_cognitive_account.openai.endpoint
}

output "openai_deployment_name" {
  value = azurerm_cognitive_deployment.agent.name
}

output "key_vault_name" {
  value = azurerm_key_vault.staging.name
}
