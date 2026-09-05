# Run long recommendation generations outside the API Gateway request deadline.
resource "aws_sqs_queue" "recommendation_dead_letter" {
  name                      = "${local.name_prefix}-recommendations-dead-letter"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true

  tags = {
    Name    = "${local.name_prefix}-recommendations-dead-letter"
    Purpose = "Disposable failed recommendation jobs"
  }
}

resource "aws_sqs_queue" "recommendations" {
  name                      = "${local.name_prefix}-recommendations"
  message_retention_seconds = 86400
  receive_wait_time_seconds = 20
  # Lambda requires SQS visibility to cover retries around the worker timeout.
  visibility_timeout_seconds = 720
  sqs_managed_sse_enabled    = true

  # Expected Runtime failures are acknowledged; retry only unexpected failures once.
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.recommendation_dead_letter.arn
    maxReceiveCount     = 2
  })

  tags = {
    Name    = "${local.name_prefix}-recommendations"
    Purpose = "Disposable asynchronous recommendation jobs"
  }
}

resource "aws_sqs_queue_redrive_allow_policy" "recommendations" {
  queue_url = aws_sqs_queue.recommendation_dead_letter.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.recommendations.arn]
  })
}

resource "aws_cloudwatch_log_group" "recommendation_worker" {
  name              = "/aws/lambda/${local.name_prefix}-recommendation-worker"
  retention_in_days = 7

  tags = {
    Name    = "${local.name_prefix}-recommendation-worker-logs"
    Purpose = "Disposable recommendation worker logs"
  }
}

resource "aws_iam_role" "recommendation_worker" {
  name               = "${local.name_prefix}-recommendation-worker"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Name    = "${local.name_prefix}-recommendation-worker"
    Purpose = "Asynchronous recommendation generation"
  }
}

data "aws_iam_policy_document" "recommendation_worker" {
  statement {
    sid    = "WriteWorkerLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.recommendation_worker.arn}:*"]
  }

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
    sid    = "CompleteRecommendationSessions"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
    ]
    resources = [aws_dynamodb_table.api_sessions.arn]
  }

  statement {
    sid    = "ConsumeRecommendationJobs"
    effect = "Allow"
    actions = [
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ReceiveMessage",
    ]
    resources = [aws_sqs_queue.recommendations.arn]
  }
}

resource "aws_iam_role_policy" "recommendation_worker" {
  name   = "${local.name_prefix}-recommendation-worker"
  role   = aws_iam_role.recommendation_worker.id
  policy = data.aws_iam_policy_document.recommendation_worker.json
}

resource "aws_lambda_function" "recommendation_worker" {
  function_name = "${local.name_prefix}-recommendation-worker"
  description   = "Private worker for asynchronous Praxis recommendations"
  role          = aws_iam_role.recommendation_worker.arn
  handler       = "praxis.functions.recommendation_worker.lambda_handler"
  runtime       = "python3.13"
  architectures = ["x86_64"]
  layers        = [local.lambda_collector_layer]

  filename         = local.api_lambda_package_path
  source_code_hash = filebase64sha256(local.api_lambda_package_path)

  memory_size = 256
  timeout     = 120

  environment {
    variables = merge(local.lambda_trace_environment, {
      PRAXIS_AGENT_RUNTIME_ARN       = aws_bedrockagentcore_agent_runtime.agent.agent_runtime_arn
      PRAXIS_AGENT_RUNTIME_QUALIFIER = aws_bedrockagentcore_agent_runtime_endpoint.stable.name
      PRAXIS_API_ACTOR_ID            = local.api_actor_id
      PRAXIS_SESSION_TABLE_NAME      = aws_dynamodb_table.api_sessions.name
    })
  }

  logging_config {
    log_format = "JSON"
  }

  tags = {
    Name    = "${local.name_prefix}-recommendation-worker"
    Purpose = "Asynchronous recommendation generation"
  }

  depends_on = [
    aws_cloudwatch_log_group.recommendation_worker,
    aws_iam_role_policy.recommendation_worker,
    aws_iam_role_policy.lambda_trace_export,
  ]
}

resource "aws_lambda_event_source_mapping" "recommendation_worker" {
  event_source_arn = aws_sqs_queue.recommendations.arn
  function_name    = aws_lambda_function.recommendation_worker.arn
  batch_size       = 1
  enabled          = true
}
