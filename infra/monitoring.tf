locals {
  namespace = var.project

  app_metrics = {
    Questions          = { pattern = "{ $.event = \"answer\" }", value = "1" }
    CostUSD            = { pattern = "{ $.event = \"answer\" }", value = "$.cost_usd" }
    AnswerErrors       = { pattern = "{ $.event = \"answer_error\" }", value = "1" }
    SearchUnavailable  = { pattern = "{ ($.event = \"answer_error\") && ($.error = \"search_unavailable\") }", value = "1" }
    EmailErrors        = { pattern = "{ $.event = \"email_error\" }", value = "1" }
    CostCapReached     = { pattern = "{ $.event = \"daily_cost_cap_reached\" }", value = "1" }
    FeedbackHelpful    = { pattern = "{ ($.event = \"feedback\") && ($.rating = 1) }", value = "1" }
    FeedbackNotHelpful = { pattern = "{ ($.event = \"feedback\") && ($.rating = -1) }", value = "1" }
  }

  job_metrics = {
    HealthChecksPassed = { pattern = "{ ($.event = \"health\") && ($.ok IS TRUE) }", value = "1" }
    JobFailures        = { pattern = "{ $.event = \"job_failed\" }", value = "1" }
  }

  count_alarms = {
    answer-errors      = { metric = "AnswerErrors", threshold = 3, period = 900, description = "3 or more answers failed in 15 minutes" }
    search-unavailable = { metric = "SearchUnavailable", threshold = 2, period = 900, description = "Search (Voyage) failed twice or more in 15 minutes" }
    email-errors       = { metric = "EmailErrors", threshold = 1, period = 900, description = "A login email couldn't be sent (SES)" }
    daily-cost-cap     = { metric = "CostCapReached", threshold = 1, period = 3600, description = "The daily cost cap was reached; the assistant is resting" }
    job-failures       = { metric = "JobFailures", threshold = 1, period = 3600, description = "A nightly job (update, cleanup or backup) failed" }
  }
}

resource "aws_sns_topic" "alarms" {
  name = "${var.project}-alarms"
}

resource "aws_sns_topic_subscription" "alarm_email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.project}/app"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "caddy" {
  name              = "/${var.project}/caddy"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "jobs" {
  name              = "/${var.project}/jobs"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_metric_filter" "app" {
  for_each       = local.app_metrics
  name           = each.key
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = each.value.pattern

  metric_transformation {
    name      = each.key
    namespace = local.namespace
    value     = each.value.value
  }
}

resource "aws_cloudwatch_log_metric_filter" "jobs" {
  for_each       = local.job_metrics
  name           = each.key
  log_group_name = aws_cloudwatch_log_group.jobs.name
  pattern        = each.value.pattern

  metric_transformation {
    name      = each.key
    namespace = local.namespace
    value     = each.value.value
  }
}

resource "aws_cloudwatch_metric_alarm" "count" {
  for_each            = local.count_alarms
  alarm_name          = "${var.project}-${each.key}"
  alarm_description   = each.value.description
  namespace           = local.namespace
  metric_name         = each.value.metric
  statistic           = "Sum"
  period              = each.value.period
  evaluation_periods  = 1
  threshold           = each.value.threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.app, aws_cloudwatch_log_metric_filter.jobs]
}

resource "aws_cloudwatch_metric_alarm" "site_down" {
  alarm_name          = "${var.project}-site-down"
  alarm_description   = "The site's health check hasn't passed for 10 minutes (server, Caddy or app down)"
  namespace           = local.namespace
  metric_name         = "HealthChecksPassed"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  actions_enabled     = var.site_monitoring_enabled
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.jobs]
}

resource "aws_cloudwatch_metric_alarm" "system_check" {
  alarm_name          = "${var.project}-server-system-check"
  alarm_description   = "AWS hardware problem; the server is recovered onto new hardware automatically"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_System"
  dimensions          = { InstanceId = aws_instance.server.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = ["arn:aws:automate:${var.region}:ec2:recover", aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "instance_check" {
  alarm_name          = "${var.project}-server-instance-check"
  alarm_description   = "The server's operating system stopped responding; it's rebooted automatically"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_Instance"
  dimensions          = { InstanceId = aws_instance.server.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = ["arn:aws:automate:${var.region}:ec2:reboot", aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "disk" {
  alarm_name          = "${var.project}-disk-80-percent"
  alarm_description   = "The server's disk is more than 80% full"
  namespace           = "CWAgent"
  metric_name         = "disk_used_percent"
  dimensions          = { InstanceId = aws_instance.server.id }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = var.project
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 8, height = 6
        properties = {
          title   = "Questions per day", region = var.region, stat = "Sum", period = 86400, view = "timeSeries"
          metrics = [[local.namespace, "Questions"]]
        }
      },
      {
        type = "metric", x = 8, y = 0, width = 8, height = 6
        properties = {
          title   = "Claude cost per day (USD)", region = var.region, stat = "Sum", period = 86400, view = "timeSeries"
          metrics = [[local.namespace, "CostUSD"]]
        }
      },
      {
        type = "metric", x = 16, y = 0, width = 8, height = 6
        properties = {
          title   = "Feedback per day", region = var.region, stat = "Sum", period = 86400, view = "timeSeries"
          metrics = [[local.namespace, "FeedbackHelpful", { label = "Helpful" }], [local.namespace, "FeedbackNotHelpful", { label = "Not helpful" }]]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 8, height = 6
        properties = {
          title = "Errors per hour", region = var.region, stat = "Sum", period = 3600, view = "timeSeries"
          metrics = [
            [local.namespace, "AnswerErrors", { label = "Answer errors" }],
            [local.namespace, "SearchUnavailable", { label = "Search unavailable" }],
            [local.namespace, "EmailErrors", { label = "Email errors" }],
          ]
        }
      },
      {
        type = "metric", x = 8, y = 6, width = 8, height = 6
        properties = {
          title   = "Site health checks passed (every 5 minutes)", region = var.region, stat = "Sum", period = 300, view = "timeSeries"
          metrics = [[local.namespace, "HealthChecksPassed"]]
        }
      },
      {
        type = "metric", x = 16, y = 6, width = 8, height = 6
        properties = {
          title = "Server", region = var.region, stat = "Average", period = 300, view = "timeSeries"
          metrics = [
            ["AWS/EC2", "CPUUtilization", "InstanceId", aws_instance.server.id, { label = "CPU %" }],
            ["CWAgent", "mem_used_percent", "InstanceId", aws_instance.server.id, { label = "Memory %" }],
            ["CWAgent", "disk_used_percent", "InstanceId", aws_instance.server.id, { label = "Disk %" }],
          ]
        }
      },
    ]
  })
}
