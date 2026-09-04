# Export deployed identifiers consumed by guarded operations and smoke tests.
output "ecr_repository_urls" {
  description = "ECR repository URLs keyed by deployable image name."
  value = {
    for name, repository in aws_ecr_repository.deployable : name => repository.repository_url
  }
}

output "api_lambda_name" {
  description = "Name of the private application API Lambda function."
  value       = aws_lambda_function.api.function_name
}

output "api_lambda_arn" {
  description = "ARN of the private application API Lambda function."
  value       = aws_lambda_function.api.arn
}

output "api_gateway_id" {
  description = "Identifier of the application HTTP API."
  value       = aws_apigatewayv2_api.application.id
}

output "api_gateway_url" {
  description = "Base URL of the application HTTP API default stage."
  value       = aws_apigatewayv2_api.application.api_endpoint
}

output "api_gateway_jwt_authorizer_id" {
  description = "Identifier of the Cognito JWT authorizer protecting application routes."
  value       = aws_apigatewayv2_authorizer.application.id
}

output "frontend_origin" {
  description = "Local browser origin allowed by the development API CORS policy."
  value       = var.frontend_origin
}

output "frontend_origins" {
  description = "Exact browser origins allowed by the development API CORS policy."
  value       = local.frontend_origins
}

output "frontend_url" {
  description = "HTTPS URL of the deployed browser application."
  value       = local.frontend_url
}

output "frontend_bucket_name" {
  description = "Private S3 bucket containing the browser application assets."
  value       = aws_s3_bucket.frontend.id
}

output "frontend_distribution_id" {
  description = "CloudFront distribution serving the browser application."
  value       = aws_cloudfront_distribution.frontend.id
}

output "cognito_user_pool_id" {
  description = "Identifier of the application Cognito user pool."
  value       = aws_cognito_user_pool.application.id
}

output "cognito_user_pool_arn" {
  description = "ARN of the application Cognito user pool."
  value       = aws_cognito_user_pool.application.arn
}

output "cognito_frontend_client_id" {
  description = "Public Cognito client identifier used by the browser application."
  value       = aws_cognito_user_pool_client.frontend.id
}

output "api_gateway_access_log_group_name" {
  description = "CloudWatch log group receiving application API access records."
  value       = aws_cloudwatch_log_group.api_gateway_access.name
}

output "catalog_table_name" {
  description = "Name of the DynamoDB table containing the disposable catalog."
  value       = aws_dynamodb_table.catalog.name
}

output "catalog_table_arn" {
  description = "ARN of the DynamoDB table containing the disposable catalog."
  value       = aws_dynamodb_table.catalog.arn
}

output "api_session_table_name" {
  description = "Name of the disposable short-lived recommendation session table."
  value       = aws_dynamodb_table.api_sessions.name
}

output "recommendation_queue_name" {
  description = "Name of the encrypted asynchronous recommendation queue."
  value       = aws_sqs_queue.recommendations.name
}

output "recommendation_worker_name" {
  description = "Name of the private asynchronous recommendation worker Lambda."
  value       = aws_lambda_function.recommendation_worker.function_name
}

output "catalog_lambda_name" {
  description = "Name of the private read-only catalog Lambda function."
  value       = aws_lambda_function.catalog.function_name
}

output "catalog_lambda_arn" {
  description = "ARN of the private read-only catalog Lambda function."
  value       = aws_lambda_function.catalog.arn
}

output "agentcore_gateway_id" {
  description = "Identifier of the IAM-authenticated AgentCore Gateway."
  value       = aws_bedrockagentcore_gateway.catalog.gateway_id
}

output "agentcore_gateway_arn" {
  description = "ARN of the IAM-authenticated AgentCore Gateway."
  value       = aws_bedrockagentcore_gateway.catalog.gateway_arn
}

output "agentcore_gateway_url" {
  description = "MCP endpoint of the IAM-authenticated AgentCore Gateway."
  value       = aws_bedrockagentcore_gateway.catalog.gateway_url
}

output "agentcore_memory_id" {
  description = "Identifier of the actor-scoped AgentCore Memory resource."
  value       = aws_bedrockagentcore_memory.personalization.id
}

output "agentcore_memory_arn" {
  description = "ARN of the actor-scoped AgentCore Memory resource."
  value       = aws_bedrockagentcore_memory.personalization.arn
}

output "agentcore_catalog_target_id" {
  description = "Identifier of the read-only catalog Lambda Gateway target."
  value       = aws_bedrockagentcore_gateway_target.catalog.target_id
}

output "agentcore_runtime_id" {
  description = "Identifier of the private AgentCore Runtime."
  value       = aws_bedrockagentcore_agent_runtime.agent.agent_runtime_id
}

output "agentcore_runtime_arn" {
  description = "ARN of the private AgentCore Runtime."
  value       = aws_bedrockagentcore_agent_runtime.agent.agent_runtime_arn
}

output "agentcore_runtime_container_uri" {
  description = "Digest-pinned ECR image used by the AgentCore Runtime."
  value       = local.agentcore_runtime_container_uri
}

output "agentcore_runtime_endpoint_arn" {
  description = "ARN of the stable version-pinned AgentCore Runtime endpoint."
  value       = aws_bedrockagentcore_agent_runtime_endpoint.stable.agent_runtime_endpoint_arn
}

output "agentcore_runtime_endpoint_name" {
  description = "Qualifier of the stable version-pinned AgentCore Runtime endpoint."
  value       = aws_bedrockagentcore_agent_runtime_endpoint.stable.name
}

output "agentcore_runtime_endpoint_version" {
  description = "Immutable Runtime version served by the stable endpoint."
  value       = aws_bedrockagentcore_agent_runtime_endpoint.stable.agent_runtime_version
}

output "ingestion_lambda_name" {
  description = "Name of the private manually invoked ingestion Lambda function."
  value       = aws_lambda_function.ingestion.function_name
}

output "source_data_bucket_name" {
  description = "Name of the disposable S3 bucket used for catalog source data."
  value       = aws_s3_bucket.source_data.id
}

output "source_data_bucket_arn" {
  description = "ARN of the disposable S3 bucket used for catalog source data."
  value       = aws_s3_bucket.source_data.arn
}
