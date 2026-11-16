# Public track-record page for Yantra Research Lab: private S3 + CloudFront, and a daily Lambda
# that reads ONE prefix of the trading system's bucket (the exported backtest feed) and writes
# ONE object (the page's JSON). Local state; terraform.tfvars holds the feed bucket name.
#
#   terraform init && terraform apply          (var.aws_profile defaults to "agentic")
#   terraform destroy                          (removes everything here; the feed is untouched)
terraform {
  required_version = ">= 1.9"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.70" }
    archive = { source = "hashicorp/archive", version = "~> 2.6" }
  }
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile
  default_tags {
    tags = { project = "agentic", app = "yantra", stack = "track-record", managed_by = "terraform" }
  }
}

data "aws_caller_identity" "this" {}
