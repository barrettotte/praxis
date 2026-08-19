variable "aws_region" {
  description = "AWS region for the temporary development environment."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "Praxis development resources must remain in us-east-1."
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
  description = "Temporary application environment represented by this root."
  type        = string
  default     = "dev"

  validation {
    condition     = var.environment == "dev"
    error_message = "This OpenTofu root manages only the dev environment."
  }
}
