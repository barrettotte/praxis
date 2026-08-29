# Define and validate inputs for the temporary development environment.
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

variable "agent_model_id" {
  description = "Bedrock model identifier used by the AgentCore Runtime."
  type        = string
  default     = "amazon.nova-micro-v1:0"

  validation {
    condition     = length(trimspace(var.agent_model_id)) > 0
    error_message = "Agent model ID must not be empty."
  }
}

variable "agent_image_digest" {
  description = "Immutable digest of the published AgentCore Runtime image."
  type        = string
  default     = "sha256:8c01abd7c3c23cef63f0e1c68b06c9549a2f10c57fd07c15eb16f1ec3ebafef6"

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.agent_image_digest))
    error_message = "Agent image digest must be a sha256 OCI digest."
  }
}
