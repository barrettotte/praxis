# Export the state bucket identity required to initialize other OpenTofu roots.
output "state_bucket_name" {
  description = "Name of the S3 bucket that stores OpenTofu state."
  value       = aws_s3_bucket.state.id
}

output "state_bucket_arn" {
  description = "ARN of the S3 bucket that stores OpenTofu state."
  value       = aws_s3_bucket.state.arn
}
