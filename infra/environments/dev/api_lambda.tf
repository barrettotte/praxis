# Deploy the private application API Lambda without a public invocation path.
locals {
  api_lambda_package_path = abspath("${path.root}/../../../build/lambda/praxis-api.zip")
}

resource "aws_cloudwatch_log_group" "api_lambda" {
  name              = "/aws/lambda/${local.name_prefix}-api"
  retention_in_days = 7

  tags = {
    Name    = "${local.name_prefix}-api-logs"
    Purpose = "Disposable application API Lambda logs"
  }
}

resource "aws_iam_role" "api_lambda" {
  name               = "${local.name_prefix}-api-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Name    = "${local.name_prefix}-api-lambda"
    Purpose = "Application API Lambda execution"
  }
}

data "aws_iam_policy_document" "api_lambda" {
  statement {
    sid    = "WriteAPIFunctionLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.api_lambda.arn}:*"]
  }

  # Both resources participate in authorization for a qualified invocation.
  statement {
    sid     = "InvokeStableAgentRuntime"
    effect  = "Allow"
    actions = ["bedrock-agentcore:InvokeAgentRuntime"]
    resources = [
      aws_bedrockagentcore_agent_runtime.agent.agent_runtime_arn,
      aws_bedrockagentcore_agent_runtime_endpoint.stable.agent_runtime_endpoint_arn,
    ]
  }

  statement {
    sid    = "ManageRecommendationSessions"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
    ]
    resources = [aws_dynamodb_table.api_sessions.arn]
  }

  statement {
    sid       = "QueueRecommendationJobs"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.recommendations.arn]
  }
}

resource "aws_iam_role_policy" "api_lambda" {
  name   = "${local.name_prefix}-api-lambda"
  role   = aws_iam_role.api_lambda.id
  policy = data.aws_iam_policy_document.api_lambda.json
}

resource "aws_lambda_function" "api" {
  function_name = "${local.name_prefix}-api"
  description   = "Private application boundary for the Praxis API"
  role          = aws_iam_role.api_lambda.arn
  handler       = "praxis.functions.api.lambda_handler"
  runtime       = "python3.13"
  architectures = ["x86_64"]

  filename         = local.api_lambda_package_path
  source_code_hash = filebase64sha256(local.api_lambda_package_path)

  memory_size = 256
  timeout     = 29

  environment {
    variables = {
      PRAXIS_AGENT_RUNTIME_ARN        = aws_bedrockagentcore_agent_runtime.agent.agent_runtime_arn
      PRAXIS_AGENT_RUNTIME_QUALIFIER  = aws_bedrockagentcore_agent_runtime_endpoint.stable.name
      PRAXIS_API_ACTOR_ID             = "praxis-single-user"
      PRAXIS_RECOMMENDATION_QUEUE_URL = aws_sqs_queue.recommendations.url
      PRAXIS_SESSION_TABLE_NAME       = aws_dynamodb_table.api_sessions.name
    }
  }

  logging_config {
    log_format = "JSON"
  }

  tags = {
    Name    = "${local.name_prefix}-api"
    Purpose = "Private application API"
  }

  depends_on = [
    aws_cloudwatch_log_group.api_lambda,
    aws_iam_role_policy.api_lambda,
  ]
}
