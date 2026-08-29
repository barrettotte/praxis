# Configure the bootstrap AWS provider and apply mandatory ownership tags.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.required_tags
  }
}
