terraform {
  required_version = ">= 1.6"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.40"
    }
  }
}

provider "azurerm" {
  features {}
  # The providers this stack needs are registered with the Azure CLI.
  # Leaving registration on makes apply wait for unrelated providers such as Microsoft.Cache.
  resource_provider_registrations = "none"
}
