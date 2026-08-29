# Store development state in the separately managed encrypted bootstrap bucket.
terraform {
  backend "s3" {
    # make tofu-init-dev injects the bucket name produced by the bootstrap root.
    key          = "praxis/dev/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
