output "ecr_repository_urls" {
  description = "ECR repository URLs keyed by deployable image name."
  value = {
    for name, repository in aws_ecr_repository.deployable : name => repository.repository_url
  }
}
