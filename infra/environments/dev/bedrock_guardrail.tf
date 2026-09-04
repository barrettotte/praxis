# Block prompt attacks at the Bedrock model boundary without filtering valid project domains.
resource "aws_bedrock_guardrail" "project_planning" {
  name                      = "${local.name_prefix}-project-planning"
  description               = "Prompt-attack protection for project recommendation and brief generation"
  blocked_input_messaging   = "The request could not be processed safely."
  blocked_outputs_messaging = "The response could not be processed safely."

  content_policy_config {
    tier_config = [{ tier_name = "CLASSIC" }]

    filters_config {
      type             = "PROMPT_ATTACK"
      input_strength   = "HIGH"
      input_action     = "BLOCK"
      input_enabled    = true
      input_modalities = ["TEXT"]
      output_strength  = "NONE"
      output_action    = "NONE"
      output_enabled   = false
    }
  }

  tags = {
    Name    = "${local.name_prefix}-project-planning"
    Purpose = "Bedrock prompt-attack protection"
  }
}

# Runtime invocations use an immutable reviewed guardrail version, not DRAFT.
resource "aws_bedrock_guardrail_version" "project_planning" {
  guardrail_arn = aws_bedrock_guardrail.project_planning.guardrail_arn
  description   = "Versioned project-planning prompt-attack policy"

  lifecycle {
    replace_triggered_by = [aws_bedrock_guardrail.project_planning]
  }
}
