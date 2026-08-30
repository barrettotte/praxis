# Store only actor-scoped preferences and decisions as explicit long-term records.
resource "aws_bedrockagentcore_memory" "personalization" {
  name                  = replace("${local.name_prefix}-personalization", "-", "_")
  description           = "Typed user preferences and prior project decisions"
  event_expiry_duration = 7

  # Indexed audit metadata supports deterministic inspection without catalog content.
  indexed_key {
    key  = "actor_id"
    type = "STRING"
  }

  indexed_key {
    key  = "kind"
    type = "STRING"
  }

  indexed_key {
    key  = "operation_id"
    type = "STRING"
  }

  indexed_key {
    key  = "session_id"
    type = "STRING"
  }

  tags = {
    Name    = "${local.name_prefix}-personalization"
    Purpose = "User preference and project decision memory"
  }
}
