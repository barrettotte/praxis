terraform {
  required_version = "= 1.12.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.60.0"
    }
  }
}
