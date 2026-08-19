locals {
  name_prefix = "${var.project_name}-${var.environment}"
  ecr_repositories = {
    agent = "AgentCore runtime image"
  }
  required_tags = {
    Environment = var.environment
    ManagedBy   = "OpenTofu"
    Project     = var.project_name
  }
}
