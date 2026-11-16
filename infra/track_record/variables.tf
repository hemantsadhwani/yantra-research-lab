variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "aws_profile" {
  type    = string
  default = "agentic"
}

variable "name" {
  type    = string
  default = "yantra-track-record"
}

variable "feed_bucket" {
  description = "Bucket the trading system exports the public feed to (set in terraform.tfvars)."
  type        = string
}

variable "feed_prefix" {
  description = "The only prefix the Lambda may read."
  type        = string
  default     = "public_feed/"
}

variable "schedule" {
  description = "When the page is rebuilt, Asia/Kolkata. The feed is exported at 16:30 IST."
  type        = string
  default     = "cron(0 17 ? * MON-FRI *)"
}
