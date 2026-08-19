variable "aws_region" {
  description = "AWS region for durable bootstrap resources."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "Praxis bootstrap resources must remain in us-east-1."
  }
}

variable "project_name" {
  description = "Lowercase project identifier used in AWS names and tags."
  type        = string
  default     = "praxis"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.project_name))
    error_message = "Project name must be 2-21 lowercase letters, digits, or hyphens."
  }
}

variable "environment" {
  description = "Lifecycle boundary represented by this OpenTofu root."
  type        = string
  default     = "bootstrap"

  validation {
    condition     = contains(["bootstrap", "dev"], var.environment)
    error_message = "Environment must be bootstrap or dev."
  }
}

variable "budget_notification_email" {
  description = "Email address that receives MVP cost-budget notifications."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[^[:space:]@]+@[^[:space:]@]+\\.[^[:space:]@]+$", var.budget_notification_email))
    error_message = "Budget notification email must be a valid email address."
  }
}
