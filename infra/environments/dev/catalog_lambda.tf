locals {
  lambda_package_path = abspath("${path.root}/../../../build/lambda/praxis-functions.zip")
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_cloudwatch_log_group" "catalog_lambda" {
  name              = "/aws/lambda/${local.name_prefix}-catalog"
  retention_in_days = 7

  tags = {
    Name    = "${local.name_prefix}-catalog-logs"
    Purpose = "Disposable catalog Lambda logs"
  }
}

resource "aws_iam_role" "catalog_lambda" {
  name               = "${local.name_prefix}-catalog-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Name    = "${local.name_prefix}-catalog-lambda"
    Purpose = "Read-only catalog Lambda execution"
  }
}

data "aws_iam_policy_document" "catalog_lambda" {
  statement {
    sid       = "ReadCatalogItems"
    effect    = "Allow"
    actions   = ["dynamodb:GetItem"]
    resources = [aws_dynamodb_table.catalog.arn]
  }

  statement {
    sid       = "QueryCatalogIndex"
    effect    = "Allow"
    actions   = ["dynamodb:Query"]
    resources = ["${aws_dynamodb_table.catalog.arn}/index/kind-date-index"]
  }

  statement {
    sid    = "WriteCatalogFunctionLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.catalog_lambda.arn}:*"]
  }
}

resource "aws_iam_role_policy" "catalog_lambda" {
  name   = "${local.name_prefix}-catalog-lambda"
  role   = aws_iam_role.catalog_lambda.id
  policy = data.aws_iam_policy_document.catalog_lambda.json
}

resource "aws_lambda_function" "catalog" {
  function_name = "${local.name_prefix}-catalog"
  description   = "Bounded read-only access to the Praxis evidence catalog"
  role          = aws_iam_role.catalog_lambda.arn
  handler       = "praxis.functions.catalog.lambda_handler"
  runtime       = "python3.13"
  architectures = ["x86_64"]

  filename         = local.lambda_package_path
  source_code_hash = filebase64sha256(local.lambda_package_path)

  memory_size = 256
  timeout     = 15

  environment {
    variables = {
      CATALOG_TABLE_NAME = aws_dynamodb_table.catalog.name
    }
  }

  logging_config {
    log_format = "JSON"
  }

  tags = {
    Name    = "${local.name_prefix}-catalog"
    Purpose = "Read-only catalog tool"
  }

  depends_on = [
    aws_cloudwatch_log_group.catalog_lambda,
    aws_iam_role_policy.catalog_lambda,
  ]
}
