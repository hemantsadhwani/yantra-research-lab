# One KMS key for the platform's data at rest: RDS, logs, ECR, SNS, secrets, S3.
resource "aws_kms_key" "this" {
  description             = "${local.name} data at rest"
  enable_key_rotation     = true
  deletion_window_in_days = var.env == "prod" ? 30 : 7
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${var.region}.amazonaws.com" }
        Action    = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
        Resource  = "*"
        Condition = { ArnLike = { "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${var.region}:${local.account_id}:*" } }
      },
      {
        Sid       = "AlertsAndBudgets"
        Effect    = "Allow"
        Principal = { Service = ["budgets.amazonaws.com", "cloudwatch.amazonaws.com", "events.amazonaws.com"] }
        Action    = ["kms:Decrypt", "kms:GenerateDataKey*"]
        Resource  = "*"
      }
    ]
  })
}

resource "aws_kms_alias" "this" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.this.key_id
}

# ---- Postgres: checkpoints, audit, memory, pgvector, and the demo warehouse schema.
# One instance, one database per app, one role per purpose (created by each app's migrate task).
resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "Postgres, reachable from app tasks only"
  vpc_id      = aws_vpc.this.id
}

resource "aws_vpc_security_group_ingress_rule" "db_from_apps" {
  security_group_id            = aws_security_group.db.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.apps.id
}

resource "aws_db_subnet_group" "this" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "pg" {
  name   = "${local.name}-pg16"
  family = "postgres16"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "500" # log any statement slower than 500 ms
  }
  parameter {
    name  = "idle_in_transaction_session_timeout"
    value = "60000"
  }
}

resource "aws_db_instance" "this" {
  identifier     = local.name
  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  allocated_storage     = 20
  max_allocated_storage = 50
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.this.arn

  db_name                             = "platform"
  username                            = "platform_admin"
  manage_master_user_password         = true # RDS keeps the password in Secrets Manager and rotates it
  master_user_secret_kms_key_id       = aws_kms_key.this.key_id
  iam_database_authentication_enabled = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  parameter_group_name   = aws_db_parameter_group.pg.name
  publicly_accessible    = false

  multi_az                   = var.db_multi_az
  backup_retention_period    = var.db_backup_days
  deletion_protection        = var.db_deletion_protection
  skip_final_snapshot        = var.env != "prod"
  final_snapshot_identifier  = "${local.name}-final"
  copy_tags_to_snapshot      = true
  auto_minor_version_upgrade = true
  apply_immediately          = var.env != "prod"
}
