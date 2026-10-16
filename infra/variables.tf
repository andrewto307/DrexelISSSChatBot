variable "account_id" {
  description = "The only AWS account this configuration may change."
  type        = string
  default     = "233202648467"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  description = "Name and tag for every resource of this project."
  type        = string
  default     = "drxl-chatbot"
}

variable "domain" {
  description = "The site's address. Login emails are sent from no-reply@ this domain."
  type        = string
  default     = "drxl-chatbot.toandrew.com"
}

variable "dns_zone" {
  description = "The domain whose DNS records are added by hand at the registrar."
  type        = string
  default     = "toandrew.com"
}

variable "alarm_email" {
  description = "Where alarms and budget warnings are sent. Set it in terraform.tfvars."
  type        = string
}

variable "github_repository" {
  description = "owner/name of the repository whose production deploys may assume the deploy role."
  type        = string
  default     = "andrewto307/DrexelISSSChatBot"
}

variable "github_owner_id" {
  description = "Permanent numeric ID of the repository's owner, part of the GitHub OIDC token's subject."
  type        = string
  default     = "183786447"
}

variable "github_repository_id" {
  description = "Permanent numeric ID of the repository, part of the GitHub OIDC token's subject."
  type        = string
  default     = "1416122830"
}

variable "instance_type" {
  type    = string
  default = "t4g.small"
}

variable "disk_size_gb" {
  type    = number
  default = 20
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "backup_retention_days" {
  type    = number
  default = 5
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "monthly_budget_usd" {
  description = "Monthly AWS budget for the whole account; warnings at 80% and 100%."
  type        = number
  default     = 25
}

variable "compose_version" {
  type    = string
  default = "v5.6.0"
}

variable "compose_sha256" {
  description = "SHA-256 of docker-compose-linux-aarch64 for compose_version."
  type        = string
  default     = "733ec76717ceb59052a9609b9dadfb523b2df8eab57a54212872d10a58078ea2"
}

variable "site_monitoring_enabled" {
  description = "Turn on the site-down alarm after the first deploy; before that the site doesn't answer yet."
  type        = bool
  default     = false
}
