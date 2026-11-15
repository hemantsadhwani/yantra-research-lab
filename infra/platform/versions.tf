# Shared AWS platform for the agentic apps (Research Lab, Agentic Reporting).
# One stack per environment: terraform init -backend-config=../environments/<env>.backend.hcl
#                             terraform apply -var-file=../environments/<env>.tfvars
terraform {
  required_version = ">= 1.9"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.70" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  backend "s3" {} # bucket/key/table come from environments/<env>.backend.hcl
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      project     = var.project
      env         = var.env
      managed_by  = "terraform"
      stack       = "platform"
      cost_center = var.cost_center
    }
  }
}

data "aws_caller_identity" "this" {}
data "aws_availability_zones" "this" { state = "available" }

locals {
  name       = "${var.project}-${var.env}"
  account_id = data.aws_caller_identity.this.account_id
  azs        = slice(data.aws_availability_zones.this.names, 0, 2)
  ssm_prefix = "/${var.project}/${var.env}/platform"
}
