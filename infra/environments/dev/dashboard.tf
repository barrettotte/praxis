# Present existing service metrics and bounded application-log aggregates without custom metrics.
resource "aws_cloudwatch_dashboard" "operations" {
  dashboard_name = "${local.name_prefix}-operations"
  dashboard_body = templatefile("${path.module}/templates/dashboard.json.tftpl", {
    region           = var.aws_region
    api_function     = aws_lambda_function.api.function_name
    worker_function  = aws_lambda_function.recommendation_worker.function_name
    catalog_function = aws_lambda_function.catalog.function_name
    api_log_group    = aws_cloudwatch_log_group.api_lambda.name
    model_id         = var.agent_model_id
  })
}

output "operations_dashboard_name" {
  description = "CloudWatch dashboard for application health and model usage."
  value       = aws_cloudwatch_dashboard.operations.dashboard_name
}
