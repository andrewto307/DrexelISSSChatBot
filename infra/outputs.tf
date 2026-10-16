locals {
  dkim_tokens = aws_sesv2_email_identity.site.dkim_signing_attributes[0].tokens

  dns_records = concat(
    [{ name = var.domain, type = "A", value = aws_eip.server.public_ip }],
    [for token in local.dkim_tokens : {
      name  = "${token}._domainkey.${var.domain}"
      type  = "CNAME"
      value = "${token}.dkim.amazonses.com"
    }],
    [
      { name = "mail.${var.domain}", type = "MX", value = "10 feedback-smtp.${var.region}.amazonses.com" },
      { name = "mail.${var.domain}", type = "TXT", value = "v=spf1 include:amazonses.com ~all" },
      { name = "_dmarc.${var.domain}", type = "TXT", value = "v=DMARC1; p=none;" },
    ],
  )
}

output "dns_records" {
  description = "Records to add by hand at the domain's DNS provider; host is the part before the zone name."
  value = [for record in local.dns_records : {
    host  = trimsuffix(record.name, ".${var.dns_zone}")
    type  = record.type
    value = record.value
  }]
}

output "github_variables" {
  description = "Variables for the GitHub production environment; none of them are secret."
  value = {
    AWS_REGION          = var.region
    AWS_DEPLOY_ROLE_ARN = aws_iam_role.deploy.arn
    ECR_REPOSITORY      = aws_ecr_repository.app.repository_url
    INSTANCE_ID         = aws_instance.server.id
    SITE_URL            = "https://${var.domain}"
  }
}

output "elastic_ip" {
  value = aws_eip.server.public_ip
}

output "backup_bucket" {
  value = aws_s3_bucket.backups.bucket
}

output "dashboard_url" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards/dashboard/${var.project}"
}
