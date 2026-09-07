# Detect HTTP API server failures using existing metrics without detailed route metrics.
resource "aws_cloudwatch_metric_alarm" "api_error_rate" {
  alarm_name          = "${local.name_prefix}-api-error-rate"
  alarm_description   = "HTTP API 5xx rate >= 5% in a five-minute period with at least five requests. Inspect API status logs and Runtime diagnostics; no automatic recovery action."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 5
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  treat_missing_data  = "notBreaching"

  # Idle development traffic is not an outage; low-volume failures remain visible in logs.
  metric_query {
    id          = "error_rate"
    expression  = "IF(requests >= 5, 100 * errors / requests, 0)"
    label       = "HTTP API 5xx percentage (minimum five requests)"
    return_data = true
  }

  metric_query {
    id          = "errors"
    return_data = false
    metric {
      namespace   = "AWS/ApiGateway"
      metric_name = "5xx"
      period      = 300
      stat        = "Sum"
      dimensions  = { ApiId = aws_apigatewayv2_api.application.id }
    }
  }

  metric_query {
    id          = "requests"
    return_data = false
    metric {
      namespace   = "AWS/ApiGateway"
      metric_name = "Count"
      period      = 300
      stat        = "Sum"
      dimensions  = { ApiId = aws_apigatewayv2_api.application.id }
    }
  }

  alarm_actions = [aws_sns_topic.operations.arn]
  ok_actions    = [aws_sns_topic.operations.arn]
  depends_on    = [aws_sns_topic_policy.operations]
}

variable "budget_notification_email" {
  description = "Same private recipient used by the bootstrap cost budget; also receives operational alerts."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[^[:space:]@]+@[^[:space:]@]+\\.[^[:space:]@]+$", var.budget_notification_email))
    error_message = "Supply the existing budget notification email as a private runtime input."
  }
}

# Alarm metadata only: no prompts or log payloads; see the notification-boundary ADR.
resource "aws_sns_topic" "operations" {
  name = "${local.name_prefix}-operations"
}

data "aws_iam_policy_document" "operations_notifications" {
  statement {
    sid       = "AllowOnlyApplicationAlarm"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.operations.arn]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
    # Construct the ARN to avoid a dependency cycle with the alarm's delivery policy.
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = ["arn:${data.aws_partition.current.partition}:cloudwatch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alarm:${local.name_prefix}-api-error-rate"]
    }
  }
}

resource "aws_sns_topic_policy" "operations" {
  arn    = aws_sns_topic.operations.arn
  policy = data.aws_iam_policy_document.operations_notifications.json
}

resource "aws_sns_topic_subscription" "operations_email" {
  topic_arn = aws_sns_topic.operations.arn
  protocol  = "email"
  endpoint  = var.budget_notification_email
}
