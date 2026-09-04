# Store short-lived recommendation sets for server-authoritative candidate selection.
resource "aws_dynamodb_table" "api_sessions" {
  name         = "${local.name_prefix}-api-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"

  deletion_protection_enabled = false

  attribute {
    name = "session_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = false
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Name    = "${local.name_prefix}-api-sessions"
    Purpose = "Disposable recommendation sessions"
  }
}
