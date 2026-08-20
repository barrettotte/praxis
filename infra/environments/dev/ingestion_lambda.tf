resource "aws_cloudwatch_log_group" "ingestion_lambda" {
  name              = "/aws/lambda/${local.name_prefix}-ingestion"
  retention_in_days = 7

  tags = {
    Name    = "${local.name_prefix}-ingestion-logs"
    Purpose = "Disposable ingestion Lambda logs"
  }
}

resource "aws_iam_role" "ingestion_lambda" {
  name               = "${local.name_prefix}-ingestion-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Name    = "${local.name_prefix}-ingestion-lambda"
    Purpose = "Catalog ingestion Lambda execution"
  }
}

data "aws_iam_policy_document" "ingestion_lambda" {
  statement {
    sid     = "ReadCatalogSources"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = [
      for object_key in ["books.json", "projects.json", "bytes.json", "museum.json"] :
      "${aws_s3_bucket.source_data.arn}/${object_key}"
    ]
  }

  statement {
    sid    = "ReconcileCatalog"
    effect = "Allow"
    actions = [
      "dynamodb:BatchWriteItem",
      "dynamodb:Scan",
    ]
    resources = [aws_dynamodb_table.catalog.arn]
  }

  statement {
    sid    = "WriteIngestionFunctionLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.ingestion_lambda.arn}:*"]
  }
}

resource "aws_iam_role_policy" "ingestion_lambda" {
  name   = "${local.name_prefix}-ingestion-lambda"
  role   = aws_iam_role.ingestion_lambda.id
  policy = data.aws_iam_policy_document.ingestion_lambda.json
}

resource "aws_lambda_function" "ingestion" {
  function_name = "${local.name_prefix}-ingestion"
  description   = "Reconcile validated source JSON into the Praxis catalog"
  role          = aws_iam_role.ingestion_lambda.arn
  handler       = "praxis.functions.ingestion.lambda_handler"
  runtime       = "python3.13"
  architectures = ["x86_64"]

  filename         = local.lambda_package_path
  source_code_hash = filebase64sha256(local.lambda_package_path)

  memory_size = 256
  timeout     = 60

  environment {
    variables = {
      CATALOG_TABLE_NAME = aws_dynamodb_table.catalog.name
      SOURCE_BUCKET_NAME = aws_s3_bucket.source_data.id
    }
  }

  logging_config {
    log_format = "JSON"
  }

  tags = {
    Name    = "${local.name_prefix}-ingestion"
    Purpose = "Manual catalog ingestion"
  }

  depends_on = [
    aws_cloudwatch_log_group.ingestion_lambda,
    aws_iam_role_policy.ingestion_lambda,
  ]
}
