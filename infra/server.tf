data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

resource "aws_instance" "server" {
  ami                         = data.aws_ssm_parameter.al2023_arm64.insecure_value
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public.id
  vpc_security_group_ids      = [aws_security_group.server.id]
  iam_instance_profile        = aws_iam_instance_profile.server.name
  associate_public_ip_address = true
  disable_api_termination     = true

  user_data = templatefile("${path.module}/cloud-init.sh.tftpl", {
    project         = var.project
    region          = var.region
    domain          = var.domain
    ecr_repository  = aws_ecr_repository.app.repository_url
    backup_bucket   = aws_s3_bucket.backups.bucket
    jobs_log_group  = aws_cloudwatch_log_group.jobs.name
    compose_version = var.compose_version
    compose_sha256  = var.compose_sha256
  })

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  credit_specification {
    cpu_credits = "standard"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.disk_size_gb
    encrypted   = true

    tags = { Name = "${var.project}-server" }
  }

  tags = { Name = "${var.project}-server" }

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}

resource "aws_eip" "server" {
  domain   = "vpc"
  instance = aws_instance.server.id

  tags = { Name = "${var.project}-server" }
}
