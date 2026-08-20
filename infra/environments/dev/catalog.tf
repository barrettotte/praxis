resource "aws_dynamodb_table" "catalog" {
  name         = "${local.name_prefix}-catalog"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "record_id"

  deletion_protection_enabled = false

  attribute {
    name = "record_id"
    type = "S"
  }

  attribute {
    name = "kind"
    type = "S"
  }

  attribute {
    name = "kind_date_key"
    type = "S"
  }

  global_secondary_index {
    name            = "kind-date-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "kind"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "kind_date_key"
      key_type       = "RANGE"
    }
  }

  point_in_time_recovery {
    enabled = false
  }

  server_side_encryption {
    enabled = true
  }

  tags = {
    Name    = "${local.name_prefix}-catalog"
    Purpose = "Disposable personal evidence catalog"
  }
}
