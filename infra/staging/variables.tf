variable "name_suffix" {
  type        = string
  description = "Lowercase letters or digits appended to globally unique Azure names."

  validation {
    condition     = can(regex("^[a-z0-9]{3,20}$", var.name_suffix))
    error_message = "Use 3 to 20 lowercase letters or digits."
  }
}

variable "location" {
  type        = string
  description = "Azure region for the staging resources."
  default     = "northeurope"
}

variable "github_repository" {
  type        = string
  description = "GitHub repository allowed to deploy staging, as owner/name."
  default     = "alexpberger/abc-prediction-platform"
}

variable "container_image" {
  type        = string
  description = "Full image reference. Leave unset on the first apply, then set it after the image is in the registry."
  default     = null
}

variable "openai_location" {
  type        = string
  description = "Region for the Azure OpenAI account. The Responses API is not enabled in North Europe."
  default     = "swedencentral"
}

variable "openai_model_name" {
  type        = string
  description = "Azure OpenAI model deployed for the local agent."
  default     = "gpt-5.4"

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]{1,64}$", var.openai_model_name))
    error_message = "Use 1 to 64 letters, digits, dots, underscores, or hyphens."
  }
}

variable "openai_model_version" {
  type        = string
  description = "Pinned model version. The deployment does not move to a newer version on its own."
  default     = "2026-03-05"

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]{1,32}$", var.openai_model_version))
    error_message = "Use 1 to 32 letters, digits, dots, underscores, or hyphens."
  }
}

variable "openai_deployment_capacity" {
  type        = number
  description = "Deployment capacity. Each unit is 1,000 tokens per minute."
  default     = 10

  validation {
    condition     = var.openai_deployment_capacity == floor(var.openai_deployment_capacity) && var.openai_deployment_capacity >= 1
    error_message = "Use a whole number of at least 1."
  }
}
