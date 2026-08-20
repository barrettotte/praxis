data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  agentcore_tool_definitions = {
    for tool in jsondecode(file("${path.module}/../../schemas/agentcore-tools.json")) :
    tool.name => tool
  }
  catalog_gateway_tools = {
    for name in [
      "search_catalog",
      "get_catalog_item",
      "summarize_experience",
      "score_project_candidates",
    ] :
    name => local.agentcore_tool_definitions[name]
  }
}

data "aws_iam_policy_document" "agentcore_gateway_assume_role" {
  statement {
    sid     = "AllowAgentCoreGateway"
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
        "arn:${data.aws_partition.current.partition}:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:gateway/*",
      ]
    }
  }
}

resource "aws_iam_role" "agentcore_gateway" {
  name               = "${local.name_prefix}-agentcore-gateway"
  description        = "Service role for the Praxis AgentCore Gateway"
  assume_role_policy = data.aws_iam_policy_document.agentcore_gateway_assume_role.json

  tags = {
    Name    = "${local.name_prefix}-agentcore-gateway"
    Purpose = "AgentCore Gateway tool invocation"
  }
}

resource "aws_bedrockagentcore_gateway" "catalog" {
  name            = "${local.name_prefix}-catalog"
  description     = "IAM-authenticated MCP boundary for Praxis catalog tools"
  role_arn        = aws_iam_role.agentcore_gateway.arn
  authorizer_type = "AWS_IAM"
  protocol_type   = "MCP"

  protocol_configuration {
    mcp {
      supported_versions = ["2025-03-26"]
    }
  }

  tags = {
    Name    = "${local.name_prefix}-catalog"
    Purpose = "Private MCP catalog tool boundary"
  }
}

data "aws_iam_policy_document" "agentcore_gateway_catalog" {
  statement {
    sid       = "InvokeCatalogLambda"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.catalog.arn]
  }
}

resource "aws_iam_role_policy" "agentcore_gateway_catalog" {
  name   = "${local.name_prefix}-invoke-catalog"
  role   = aws_iam_role.agentcore_gateway.id
  policy = data.aws_iam_policy_document.agentcore_gateway_catalog.json
}

resource "aws_bedrockagentcore_gateway_target" "catalog" {
  name               = "${local.name_prefix}-catalog"
  description        = "Read-only access to the Praxis evidence catalog"
  gateway_identifier = aws_bedrockagentcore_gateway.catalog.gateway_id

  credential_provider_configuration {
    gateway_iam_role {}
  }

  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.catalog.arn

        tool_schema {
          dynamic "inline_payload" {
            for_each = local.catalog_gateway_tools

            content {
              name        = inline_payload.value.name
              description = inline_payload.value.description

              input_schema {
                type        = inline_payload.value.inputSchema.type
                description = try(inline_payload.value.inputSchema.description, null)

                dynamic "property" {
                  for_each = inline_payload.value.inputSchema.properties
                  iterator = top_property

                  content {
                    name        = top_property.key
                    type        = top_property.value.type
                    description = try(top_property.value.description, null)
                    required    = contains(inline_payload.value.inputSchema.required, top_property.key)

                    dynamic "items" {
                      for_each = top_property.value.type == "array" ? [top_property.value.items] : []
                      iterator = array_items

                      content {
                        type        = array_items.value.type
                        description = try(array_items.value.description, null)

                        dynamic "property" {
                          for_each = {
                            for name, definition in try(array_items.value.properties, {}) :
                            name => definition if array_items.value.type == "object"
                          }
                          iterator = item_property

                          content {
                            name            = item_property.key
                            type            = item_property.value.type
                            description     = try(item_property.value.description, null)
                            required        = contains(try(array_items.value.required, []), item_property.key)
                            items_json      = item_property.value.type == "array" ? jsonencode(item_property.value.items) : null
                            properties_json = item_property.value.type == "object" ? jsonencode({ properties = item_property.value.properties, required = try(item_property.value.required, []) }) : null
                          }
                        }
                      }
                    }

                    dynamic "property" {
                      for_each = {
                        for name, definition in try(top_property.value.properties, {}) :
                        name => definition if top_property.value.type == "object"
                      }
                      iterator = object_property

                      content {
                        name            = object_property.key
                        type            = object_property.value.type
                        description     = try(object_property.value.description, null)
                        required        = contains(try(top_property.value.required, []), object_property.key)
                        items_json      = object_property.value.type == "array" ? jsonencode(object_property.value.items) : null
                        properties_json = object_property.value.type == "object" ? jsonencode({ properties = object_property.value.properties, required = try(object_property.value.required, []) }) : null
                      }
                    }
                  }
                }
              }

              output_schema {
                type        = inline_payload.value.outputSchema.type
                description = try(inline_payload.value.outputSchema.description, null)

                dynamic "property" {
                  for_each = inline_payload.value.outputSchema.properties
                  iterator = top_property

                  content {
                    name        = top_property.key
                    type        = top_property.value.type
                    description = try(top_property.value.description, null)
                    required    = contains(inline_payload.value.outputSchema.required, top_property.key)

                    dynamic "items" {
                      for_each = top_property.value.type == "array" ? [top_property.value.items] : []
                      iterator = array_items

                      content {
                        type        = array_items.value.type
                        description = try(array_items.value.description, null)

                        dynamic "property" {
                          for_each = {
                            for name, definition in try(array_items.value.properties, {}) :
                            name => definition if array_items.value.type == "object"
                          }
                          iterator = item_property

                          content {
                            name            = item_property.key
                            type            = item_property.value.type
                            description     = try(item_property.value.description, null)
                            required        = contains(try(array_items.value.required, []), item_property.key)
                            items_json      = item_property.value.type == "array" ? jsonencode(item_property.value.items) : null
                            properties_json = item_property.value.type == "object" ? jsonencode({ properties = item_property.value.properties, required = try(item_property.value.required, []) }) : null
                          }
                        }
                      }
                    }

                    dynamic "property" {
                      for_each = {
                        for name, definition in try(top_property.value.properties, {}) :
                        name => definition if top_property.value.type == "object"
                      }
                      iterator = object_property

                      content {
                        name            = object_property.key
                        type            = object_property.value.type
                        description     = try(object_property.value.description, null)
                        required        = contains(try(top_property.value.required, []), object_property.key)
                        items_json      = object_property.value.type == "array" ? jsonencode(object_property.value.items) : null
                        properties_json = object_property.value.type == "object" ? jsonencode({ properties = object_property.value.properties, required = try(object_property.value.required, []) }) : null
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }

  depends_on = [aws_iam_role_policy.agentcore_gateway_catalog]
}
