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

  # API Gateway owns preflight responses and appends these headers to integrations.
  cors_configuration {
    allow_headers = [
      "authorization",
      "content-type",
      "x-correlation-id",
    ]
    allow_methods  = ["GET", "OPTIONS", "POST"]
    allow_origins  = [var.frontend_origin]
    expose_headers = ["x-correlation-id"]
    max_age        = 300
  }

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

# Accept tokens only from the application user pool and public browser client.
resource "aws_apigatewayv2_authorizer" "application" {
  api_id           = aws_apigatewayv2_api.application.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${local.name_prefix}-cognito"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.frontend.id]
    issuer   = "https://${aws_cognito_user_pool.application.endpoint}"
  }
}

resource "aws_apigatewayv2_route" "application" {
  for_each = local.api_routes

  api_id             = aws_apigatewayv2_api.application.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.api_lambda.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.application.id
}

resource "aws_cloudwatch_log_group" "api_gateway_access" {
  name              = "/aws/apigateway/${local.name_prefix}-api-access"
  retention_in_days = 7

  tags = {
    Name    = "${local.name_prefix}-api-access-logs"
    Purpose = "Disposable application API access logs"
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.application.id
  name        = "$default"
  auto_deploy = true

  # Record operational fields only; omit request content and caller identifiers.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway_access.arn
    format = jsonencode({
      http_method            = "$context.httpMethod"
      integration_latency_ms = "$context.integration.latency"
      integration_request_id = "$context.integration.requestId"
      integration_status     = "$context.integration.status"
      request_id             = "$context.requestId"
      request_time_epoch_ms  = "$context.requestTimeEpoch"
      response_latency_ms    = "$context.responseLatency"
      response_length_bytes  = "$context.responseLength"
      route_key              = "$context.routeKey"
      status                 = "$context.status"
    })
  }

  # A single-user session route should not start concurrent metered agent runs.
  route_settings {
    route_key              = "POST /v1/sessions"
    throttling_burst_limit = 1
    throttling_rate_limit  = 0.1
  }

  route_settings {
    route_key              = "POST /v1/projects/{candidateId}/select"
    throttling_burst_limit = 1
    throttling_rate_limit  = 0.1
  }

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
