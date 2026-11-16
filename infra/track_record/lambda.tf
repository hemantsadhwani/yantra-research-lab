# The page rebuilder. Stdlib + boto3 (in the runtime), so the zip is just the three modules.
data "archive_file" "lambda" {
  type        = "zip"
  output_path = "${path.module}/build/lambda.zip"
  source {
    content  = file("${path.module}/../../track_record/__init__.py")
    filename = "track_record/__init__.py"
  }
  source {
    content  = file("${path.module}/../../track_record/ledger.py")
    filename = "track_record/ledger.py"
  }
  source {
    content  = file("${path.module}/../../track_record/build.py")
    filename = "track_record/build.py"
  }
}

data "aws_iam_policy_document" "assume_lambda" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

# Least privilege: read the feed prefix, write the one JSON object, write its own logs.
data "aws_iam_policy_document" "lambda" {
  statement {
    sid       = "ReadFeedOnly"
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::${var.feed_bucket}/${var.feed_prefix}*"]
  }
  statement {
    sid       = "WritePageData"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.site.arn}/data/track_record.json"]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = 14
}

resource "aws_lambda_function" "rebuild" {
  function_name    = var.name
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "track_record.build.handler"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  timeout          = 30
  memory_size      = 256
  environment {
    variables = {
      FEED_BUCKET = var.feed_bucket
      FEED_PREFIX = var.feed_prefix
      SITE_BUCKET = aws_s3_bucket.site.id
    }
  }
  depends_on = [aws_cloudwatch_log_group.lambda]
}

# Weekday schedule (EventBridge Scheduler, IST)
data "aws_iam_policy_document" "assume_scheduler" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.this.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.assume_scheduler.json
}

resource "aws_iam_role_policy" "scheduler" {
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "lambda:InvokeFunction", Resource = aws_lambda_function.rebuild.arn }]
  })
}

resource "aws_scheduler_schedule" "daily" {
  name                         = var.name
  schedule_expression          = var.schedule
  schedule_expression_timezone = "Asia/Kolkata"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.rebuild.arn
    role_arn = aws_iam_role.scheduler.arn
    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}
