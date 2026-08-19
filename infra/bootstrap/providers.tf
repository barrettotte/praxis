provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.required_tags
  }
}
