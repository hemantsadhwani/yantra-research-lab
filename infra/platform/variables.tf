variable "project" {
  type    = string
  default = "agentic"
}
variable "env" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env is dev or prod. Environments differ by tfvars, never by code."
  }
}
variable "region" {
  type    = string
  default = "ap-south-1" # Mumbai: data stays in India
}
variable "cost_center" {
  type    = string
  default = "ai-platform"
}
variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}
variable "endpoint_az_count" {
  description = "Interface endpoints are billed per AZ. dev = 1 to save cost, prod = 2 for HA."
  type        = number
  default     = 1
}

# ---- database
variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}
variable "db_engine_version" {
  type    = string
  default = "16"
}
variable "db_multi_az" {
  type    = bool
  default = false
}
variable "db_backup_days" {
  type    = number
  default = 1
}
variable "db_deletion_protection" {
  type    = bool
  default = false
}

# ---- identity: Cognito groups are the RBAC roles every app reads from the token
variable "roles" {
  type = map(string)
  default = {
    "platform-admin"  = "Operate the platform"
    "report-approver" = "Approve or reject a report at the publish gate"
    "report-analyst"  = "Run reports and read drafts; cannot approve"
    "lab-approver"    = "Approve or reject a strategy promotion"
    "viewer"          = "Read published output only"
  }
}

# ---- ops
variable "alert_email" {
  description = "Receives budget, alarm and approval notifications. Empty = no subscription."
  type        = string
  default     = ""
}
variable "monthly_budget_usd" {
  type    = number
  default = 30
}
variable "container_insights" {
  type    = bool
  default = false
}
variable "ecr_repos" {
  type    = list(string)
  default = ["reporting", "lab-backend", "lab-runner"]
}

# ---- CI
variable "github_owner" {
  type    = string
  default = "hemantsadhwani"
}
variable "github_repos" {
  type    = list(string)
  default = ["agentic-reporting", "yantra-research-lab"]
}
variable "create_github_oidc_provider" {
  description = "Only one GitHub OIDC provider may exist per account. Set false if it already exists."
  type        = bool
  default     = true
}
