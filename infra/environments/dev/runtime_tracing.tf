# Deliver managed Runtime invocation spans independently of the container's ADOT export.
resource "aws_cloudwatch_log_delivery_source" "runtime_traces" {
  name         = "${local.name_prefix}-runtime-traces"
  log_type     = "TRACES"
  resource_arn = aws_bedrockagentcore_agent_runtime.agent.agent_runtime_arn
}

# Keep this lifecycle independent of Gateway delivery; do not enable payload-bearing logs.
resource "aws_cloudwatch_log_delivery_destination" "runtime_traces" {
  name                      = "${local.name_prefix}-runtime-traces"
  delivery_destination_type = "XRAY"
}

resource "aws_cloudwatch_log_delivery" "runtime_traces" {
  delivery_source_name     = aws_cloudwatch_log_delivery_source.runtime_traces.name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.runtime_traces.arn
}
