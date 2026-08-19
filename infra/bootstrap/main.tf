data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  state_bucket_name = "${var.project_name}-tofu-state-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  state_bucket_arn  = "arn:${data.aws_partition.current.partition}:s3:::${local.state_bucket_name}"
  required_tags = {
    Environment = var.environment
    ManagedBy   = "OpenTofu"
    Project     = var.project_name
  }
}

resource "aws_s3_bucket" "state" {
  bucket        = local.state_bucket_name
  force_destroy = true

  tags = {
    Name    = local.state_bucket_name
    Purpose = "OpenTofuState"
  }
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket = aws_s3_bucket.state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

data "aws_iam_policy_document" "state" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      local.state_bucket_arn,
      "${local.state_bucket_arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.state.json

  depends_on = [aws_s3_bucket_public_access_block.state]
}
