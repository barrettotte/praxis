resource "aws_ecr_repository" "deployable" {
  for_each = local.ecr_repositories

  name                 = "${local.name_prefix}-${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  encryption_configuration {
    encryption_type = "AES256"
  }

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name    = "${local.name_prefix}-${each.key}"
    Purpose = each.value
  }
}

resource "aws_ecr_lifecycle_policy" "deployable" {
  for_each = aws_ecr_repository.deployable

  repository = each.value.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged development images after seven days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Retain only the ten newest development images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      },
    ]
  })
}
