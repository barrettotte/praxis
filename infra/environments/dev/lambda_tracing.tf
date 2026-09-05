# Export application-only Lambda spans through a pinned collector extension.
locals {
  lambda_collector_layer = "arn:aws:lambda:us-east-1:901920570463:layer:aws-otel-collector-amd64-ver-0-156-0:4"
  lambda_trace_environment = {
    PRAXIS_LAMBDA_TRACING              = "true"
    OPENTELEMETRY_COLLECTOR_CONFIG_URI = "file:/var/task/collector.yaml"
  }
}

data "aws_iam_policy_document" "lambda_trace_export" {
  statement {
    sid     = "ExportApplicationTraces"
    effect  = "Allow"
    actions = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    # X-Ray ingestion does not support resource-level permissions.
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "lambda_trace_export" {
  for_each = {
    api     = aws_iam_role.api_lambda.id
    worker  = aws_iam_role.recommendation_worker.id
    catalog = aws_iam_role.catalog_lambda.id
  }
  name   = "${local.name_prefix}-trace-export"
  role   = each.value
  policy = data.aws_iam_policy_document.lambda_trace_export.json
}
