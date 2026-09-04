# Centralize development naming, deployable images, and mandatory resource tags.
locals {
  api_actor_id = "praxis-single-user"
  name_prefix  = "${var.project_name}-${var.environment}"
  ecr_repositories = {
    agent = "AgentCore runtime image"
  }
  required_tags = {
    Environment = var.environment
    ManagedBy   = "OpenTofu"
    Project     = var.project_name
  }
}
