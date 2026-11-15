# prod: same code, different sizes. High availability and protection switched on.
env                    = "prod"
vpc_cidr               = "10.41.0.0/16"
endpoint_az_count      = 2
db_instance_class      = "db.t4g.small"
db_multi_az            = true
db_backup_days         = 7
db_deletion_protection = true
monthly_budget_usd     = 150
container_insights     = true
