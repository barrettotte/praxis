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

variable "frontend_origin" {
  description = "Exact browser origin allowed to call the development HTTP API."
  type        = string
  default     = "http://localhost:5173"

  validation {
    condition = (
      can(regex("^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$", var.frontend_origin)) ||
      can(regex("^http://localhost(:[0-9]{1,5})?$", var.frontend_origin))
    )
    error_message = "Frontend origin must be HTTPS or an HTTP localhost origin without a path."
  }
}

variable "agent_model_id" {
  description = "Bedrock model identifier used by the AgentCore Runtime."
  type        = string
  default     = "amazon.nova-lite-v1:0"

  validation {
    condition     = length(trimspace(var.agent_model_id)) > 0
    error_message = "Agent model ID must not be empty."
  }
}

variable "agent_image_digest" {
  description = "Immutable digest of the published AgentCore Runtime image."
  type        = string
  default     = "sha256:9de33f61222a79f54df08cdf9c4ccd2768512260e4310a1f5c8095bb97389e1c"

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.agent_image_digest))
    error_message = "Agent image digest must be a sha256 OCI digest."
  }
}

variable "agent_runtime_endpoint_version" {
  description = "Verified immutable Runtime version promoted to the stable endpoint."
  type        = string
  default     = "38"

  validation {
    condition     = can(regex("^[1-9][0-9]{0,4}$", var.agent_runtime_endpoint_version))
    error_message = "Agent Runtime endpoint version must be an integer from 1 to 99999."
  }
}
