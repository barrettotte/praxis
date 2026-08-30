# Expose the application Lambda through a low-cost HTTP API with explicit routes.
locals {
  api_routes = toset([
    "GET /v1/sessions/{sessionId}",
    "POST /v1/projects/{candidateId}/select",
    "POST /v1/sessions",
    "POST /v1/sessions/{sessionId}/messages",
  ])
}

resource "aws_apigatewayv2_api" "application" {
  name          = "${local.name_prefix}-api"
  description   = "Application boundary for the Praxis API"
  protocol_type = "HTTP"

  tags = {
    Name    = "${local.name_prefix}-api"
    Purpose = "Application HTTP API"
  }
}

resource "aws_apigatewayv2_integration" "api_lambda" {
  api_id                 = aws_apigatewayv2_api.application.id
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "application" {
  for_each = local.api_routes

  api_id    = aws_apigatewayv2_api.application.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.application.id
  name        = "$default"
  auto_deploy = true

  tags = {
    Name    = "${local.name_prefix}-api-default"
    Purpose = "Application HTTP API deployment"
  }
}

# Permit invocation only through this API; the Lambda has no function URL.
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowApplicationAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.application.execution_arn}/*/*"
}
