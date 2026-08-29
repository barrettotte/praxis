# Enforce the project-wide cost target with durable email notifications.
resource "aws_budgets_budget" "mvp" {
  name         = "${var.project_name}-mvp-annual"
  budget_type  = "COST"
  limit_amount = "10"
  limit_unit   = "USD"
  time_unit    = "ANNUALLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_notification_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_notification_email]
  }

  tags = {
    Name    = "${var.project_name}-mvp-annual"
    Purpose = "MVP cost control"
  }
}
