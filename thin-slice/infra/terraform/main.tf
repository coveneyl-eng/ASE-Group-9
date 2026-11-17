# Azure EU-region footprint from the technical architecture (thin slice: smallest SKUs).
#   cd infra/terraform && terraform init && terraform validate && terraform plan
terraform {
  required_version = ">= 1.6"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

variable "subscription_id" { type = string }
variable "prefix" {
  type    = string
  default = "ase9smartcity"
}
variable "location" {
  type    = string
  default = "northeurope" # Dublin
}

data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "rg" {
  name     = "${var.prefix}-rg"
  location = var.location
}

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "${var.prefix}-logs"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_registry" "acr" {
  name                = "${var.prefix}acr"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "Basic"
}

resource "azurerm_kubernetes_cluster" "aks" {
  name                = "${var.prefix}-aks"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  dns_prefix          = var.prefix
  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  default_node_pool {
    name       = "system"
    node_count = 2 # two copies of each core component (99.9% availability target)
    vm_size    = "Standard_B2s"
    zones      = ["1", "2"]
  }
  identity { type = "SystemAssigned" }
  oms_agent { log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id } # Azure Monitor
}

resource "azurerm_role_assignment" "aks_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.aks.kubelet_identity[0].object_id
}

resource "azurerm_storage_account" "blob" {
  name                     = "${var.prefix}blob"
  location                 = azurerm_resource_group.rg.location
  resource_group_name      = azurerm_resource_group.rg.name
  account_tier             = "Standard"
  account_replication_type = "ZRS"
  min_tls_version          = "TLS1_2"
}

resource "azurerm_storage_container" "containers" {
  for_each              = toset(["reports", "static-layers", "backups"])
  name                  = each.key
  storage_account_id    = azurerm_storage_account.blob.id
  container_access_type = "private"
}

resource "azurerm_key_vault" "kv" {
  name                      = "${var.prefix}-kv"
  location                  = azurerm_resource_group.rg.location
  resource_group_name       = azurerm_resource_group.rg.name
  tenant_id                 = data.azurerm_client_config.current.tenant_id
  sku_name                  = "standard"
  enable_rbac_authorization = true
  purge_protection_enabled  = false
}

output "acr_login_server" { value = azurerm_container_registry.acr.login_server }
output "key_vault_url" { value = azurerm_key_vault.kv.vault_uri }
output "aks_name" { value = azurerm_kubernetes_cluster.aks.name }
