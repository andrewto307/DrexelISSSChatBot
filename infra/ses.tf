resource "aws_sesv2_email_identity" "site" {
  email_identity = var.domain
}

resource "aws_sesv2_email_identity_mail_from_attributes" "site" {
  email_identity         = aws_sesv2_email_identity.site.email_identity
  mail_from_domain       = "mail.${var.domain}"
  behavior_on_mx_failure = "USE_DEFAULT_VALUE"
}
