# Hold encrypted, private, reproducible source copies for catalog ingestion.
resource "aws_s3_bucket" "source_data" {
  bucket_prefix = "${local.name_prefix}-source-data-"
  # Authoritative data lives outside AWS, so confirmed teardown removes all copies.
  force_destroy = true

  tags = {
    Name    = "${local.name_prefix}-source-data"
    Purpose = "Disposable source data for catalog ingestion"
  }
}

resource "aws_s3_bucket_ownership_controls" "source_data" {
  bucket = aws_s3_bucket.source_data.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "source_data" {
  bucket = aws_s3_bucket.source_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "source_data" {
  bucket = aws_s3_bucket.source_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "source_data" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.source_data.arn,
      "${aws_s3_bucket.source_data.arn}/*",
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "source_data" {
  bucket = aws_s3_bucket.source_data.id
  policy = data.aws_iam_policy_document.source_data.json

  depends_on = [aws_s3_bucket_public_access_block.source_data]
}
