output "ecr_repository_urls" {
  description = "ECR repository URLs keyed by deployable image name."
  value = {
    for name, repository in aws_ecr_repository.deployable : name => repository.repository_url
  }
}

output "catalog_table_name" {
  description = "Name of the DynamoDB table containing the disposable catalog."
  value       = aws_dynamodb_table.catalog.name
}

output "catalog_table_arn" {
  description = "ARN of the DynamoDB table containing the disposable catalog."
  value       = aws_dynamodb_table.catalog.arn
}

output "catalog_lambda_name" {
  description = "Name of the private read-only catalog Lambda function."
  value       = aws_lambda_function.catalog.function_name
}

output "catalog_lambda_arn" {
  description = "ARN of the private read-only catalog Lambda function."
  value       = aws_lambda_function.catalog.arn
}

output "ingestion_lambda_name" {
  description = "Name of the private manually invoked ingestion Lambda function."
  value       = aws_lambda_function.ingestion.function_name
}

output "source_data_bucket_name" {
  description = "Name of the disposable S3 bucket used for catalog source data."
  value       = aws_s3_bucket.source_data.id
}

output "source_data_bucket_arn" {
  description = "ARN of the disposable S3 bucket used for catalog source data."
  value       = aws_s3_bucket.source_data.arn
}
