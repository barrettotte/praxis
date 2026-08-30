# Run the digest-pinned Strands agent with bounded, least-privilege AWS access.
locals {
  agentcore_runtime_name          = replace("${local.name_prefix}-agent", "-", "_")
  agentcore_runtime_container_uri = "${aws_ecr_repository.deployable["agent"].repository_url}@${var.agent_image_digest}"
  # Keep the measured Micro fallback callable alongside the configured default.
  agentcore_runtime_model_ids = distinct([
    "amazon.nova-micro-v1:0",
    var.agent_model_id,
  ])
  agentcore_runtime_environment = {
    AGENT_OBSERVABILITY_ENABLED = "true"
    AWS_REGION                  = var.aws_region
    OTEL_EXPORTER_OTLP_PROTOCOL = "http/protobuf"
    OTEL_PYTHON_CONFIGURATOR    = "aws_configurator"
    OTEL_PYTHON_DISTRO          = "aws_distro"
    PRAXIS_GATEWAY_URL          = aws_bedrockagentcore_gateway.catalog.gateway_url
    PRAXIS_MAX_CATALOG_RESULTS  = "20"
    PRAXIS_MAX_TOOL_CALLS       = "4"
    PRAXIS_MODEL_ID             = var.agent_model_id
  }
  # Short development sessions limit idle compute while preserving useful continuity.
  agentcore_runtime_lifecycle = {
    idle_runtime_session_timeout = 300
    max_lifetime                 = 3600
  }
}

# Source constraints prevent confused-deputy use by unrelated AgentCore resources.
data "aws_iam_policy_document" "agentcore_runtime_assume_role" {
  statement {
    sid     = "AllowAgentCoreRuntime"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values = [
        "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:runtime/${local.agentcore_runtime_name}-*",
      ]
    }
  }
}

resource "aws_iam_role" "agentcore_runtime" {
  name               = "${local.name_prefix}-agentcore-runtime"
  description        = "Execution role for the Praxis AgentCore Runtime"
  assume_role_policy = data.aws_iam_policy_document.agentcore_runtime_assume_role.json

  tags = {
    Name    = "${local.name_prefix}-agentcore-runtime"
    Purpose = "AgentCore Runtime execution"
  }
}

data "aws_iam_policy_document" "agentcore_runtime" {
  statement {
    sid       = "PullAgentImage"
    effect    = "Allow"
    actions   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [aws_ecr_repository.deployable["agent"].arn]
  }

  statement {
    sid       = "GetECRToken"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "ManageRuntimeLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:DescribeLogStreams",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*",
    ]
  }

  statement {
    sid     = "ConfigureRuntimeLogs"
    effect  = "Allow"
    actions = ["logs:PutResourcePolicy"]
    resources = [
      "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/${local.agentcore_runtime_name}-*",
    ]
  }

  statement {
    sid     = "DiscoverRuntimeLogs"
    effect  = "Allow"
    actions = ["logs:DescribeLogGroups"]
    resources = [
      "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:*",
    ]
  }

  statement {
    sid    = "WriteRuntimeLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*",
    ]
  }

  statement {
    sid    = "InvokeConfiguredModels"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = [
      for model_id in local.agentcore_runtime_model_ids :
      "arn:${data.aws_partition.current.partition}:bedrock:${var.aws_region}::foundation-model/${model_id}"
    ]
  }

  statement {
    sid       = "InvokeCatalogGateway"
    effect    = "Allow"
    actions   = ["bedrock-agentcore:InvokeGateway"]
    resources = [aws_bedrockagentcore_gateway.catalog.gateway_arn]
  }

  # ADOT sends Strands spans to X-Ray for CloudWatch and AgentCore Evaluations.
  statement {
    sid    = "WriteRuntimeTraces"
    effect = "Allow"
    actions = [
      "xray:GetSamplingRules",
      "xray:GetSamplingTargets",
      "xray:PutTelemetryRecords",
      "xray:PutTraceSegments",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "agentcore_runtime" {
  name   = "${local.name_prefix}-agent-runtime"
  role   = aws_iam_role.agentcore_runtime.id
  policy = data.aws_iam_policy_document.agentcore_runtime.json
}

resource "aws_bedrockagentcore_agent_runtime" "agent" {
  agent_runtime_name = local.agentcore_runtime_name
  description        = "Evidence-backed project recommendation agent"
  role_arn           = aws_iam_role.agentcore_runtime.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = local.agentcore_runtime_container_uri
    }
  }

  environment_variables = local.agentcore_runtime_environment

  lifecycle_configuration {
    idle_runtime_session_timeout = local.agentcore_runtime_lifecycle.idle_runtime_session_timeout
    max_lifetime                 = local.agentcore_runtime_lifecycle.max_lifetime
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  protocol_configuration {
    server_protocol = "HTTP"
  }

  tags = {
    Name    = local.agentcore_runtime_name
    Purpose = "Private Strands agent hosting"
  }

  depends_on = [aws_iam_role_policy.agentcore_runtime]
}

# The AWS provider cannot yet send Runtime metadataConfiguration. Keep this
# update attached to the declared configuration until the provider exposes it.
resource "terraform_data" "agentcore_runtime_mmdsv2" {
  triggers_replace = [
    sha256(jsonencode({
      container_uri = local.agentcore_runtime_container_uri
      environment   = local.agentcore_runtime_environment
      lifecycle     = local.agentcore_runtime_lifecycle
      role_arn      = aws_iam_role.agentcore_runtime.arn
      runtime_id    = aws_bedrockagentcore_agent_runtime.agent.agent_runtime_id
    })),
  ]

  provisioner "local-exec" {
    command = "${path.module}/../../../scripts/enable-agent-runtime-mmdsv2.sh"

    environment = {
      PRAXIS_AGENT_CONTAINER_URI     = local.agentcore_runtime_container_uri
      PRAXIS_AGENT_GATEWAY_URL       = aws_bedrockagentcore_gateway.catalog.gateway_url
      PRAXIS_AGENT_IDLE_TIMEOUT      = tostring(local.agentcore_runtime_lifecycle.idle_runtime_session_timeout)
      PRAXIS_AGENT_MAX_LIFETIME      = tostring(local.agentcore_runtime_lifecycle.max_lifetime)
      PRAXIS_AGENT_MAX_RESULTS       = local.agentcore_runtime_environment.PRAXIS_MAX_CATALOG_RESULTS
      PRAXIS_AGENT_MAX_TOOL_CALLS    = local.agentcore_runtime_environment.PRAXIS_MAX_TOOL_CALLS
      PRAXIS_AGENT_MODEL_ID          = var.agent_model_id
      PRAXIS_AGENT_OBSERVABILITY     = local.agentcore_runtime_environment.AGENT_OBSERVABILITY_ENABLED
      PRAXIS_AGENT_OTEL_CONFIGURATOR = local.agentcore_runtime_environment.OTEL_PYTHON_CONFIGURATOR
      PRAXIS_AGENT_OTEL_DISTRO       = local.agentcore_runtime_environment.OTEL_PYTHON_DISTRO
      PRAXIS_AGENT_OTEL_PROTOCOL     = local.agentcore_runtime_environment.OTEL_EXPORTER_OTLP_PROTOCOL
      PRAXIS_AGENT_ROLE_ARN          = aws_iam_role.agentcore_runtime.arn
      PRAXIS_AGENT_RUNTIME_ID        = aws_bedrockagentcore_agent_runtime.agent.agent_runtime_id
      PRAXIS_AGENT_RUNTIME_REGION    = var.aws_region
    }
  }
}

# A named endpoint stays on a reviewed version while newer Runtime versions are tested.
resource "aws_bedrockagentcore_agent_runtime_endpoint" "stable" {
  name                  = "stable"
  agent_runtime_id      = aws_bedrockagentcore_agent_runtime.agent.agent_runtime_id
  agent_runtime_version = var.agent_runtime_endpoint_version
  description           = "Stable endpoint for the verified Praxis agent version"

  tags = {
    Name    = "${local.agentcore_runtime_name}_stable"
    Purpose = "Pinned AgentCore Runtime promotion"
  }

  depends_on = [terraform_data.agentcore_runtime_mmdsv2]
}
