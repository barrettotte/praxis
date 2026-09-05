# Deliver Gateway service spans through X-Ray to the configured CloudWatch trace store.
resource "aws_cloudwatch_log_delivery_source" "gateway_traces" {
  name         = "${local.name_prefix}-gateway-traces"
  log_type     = "TRACES"
  resource_arn = aws_bedrockagentcore_gateway.catalog.gateway_arn
}

# XRAY uses the account's existing Transaction Search destination, not a new log group.
# Do not enable content-bearing APPLICATION_LOGS as part of trace delivery.
resource "aws_cloudwatch_log_delivery_destination" "gateway_traces" {
  name                      = "${local.name_prefix}-gateway-traces"
  delivery_destination_type = "XRAY"
}

resource "aws_cloudwatch_log_delivery" "gateway_traces" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.gateway_traces.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.gateway_traces.arn
}
