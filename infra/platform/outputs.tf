# Apps read these from SSM Parameter Store, not from this stack's state file. The platform team
# and the app teams can then change their stacks independently.
locals {
  exports = {
    vpc_id               = aws_vpc.this.id
    private_subnet_ids   = join(",", aws_subnet.private[*].id)
    apps_sg_id           = aws_security_group.apps.id
    kms_key_arn          = aws_kms_key.this.arn
    ecs_cluster_arn      = aws_ecs_cluster.this.arn
    ecs_cluster_name     = aws_ecs_cluster.this.name
    alb_listener_arn     = aws_lb_listener.http.arn
    api_endpoint         = aws_apigatewayv2_api.this.api_endpoint
    db_address           = aws_db_instance.this.address
    db_port              = tostring(aws_db_instance.this.port)
    db_master_secret_arn = aws_db_instance.this.master_user_secret[0].secret_arn
    db_resource_id       = aws_db_instance.this.resource_id
    user_pool_id         = aws_cognito_user_pool.this.id
    user_pool_client_id  = aws_cognito_user_pool_client.cli.id
    alerts_topic_arn     = aws_sns_topic.alerts.arn
    ci_deploy_role_arn   = aws_iam_role.ci_deploy.arn
    ecr_registry         = "${local.account_id}.dkr.ecr.${var.region}.amazonaws.com"
  }
}

resource "aws_ssm_parameter" "export" {
  for_each = local.exports
  name     = "${local.ssm_prefix}/${each.key}"
  type     = "String"
  value    = each.value
}

output "exports" {
  value = local.exports
}
