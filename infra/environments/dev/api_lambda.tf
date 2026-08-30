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
  timeout     = 30

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
