terraform {
  backend "s3" {
    key          = "praxis/dev/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
