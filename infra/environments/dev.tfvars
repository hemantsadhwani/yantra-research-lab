# dev: cheapest shape that is still the real architecture. Deploy, record evidence, destroy.
env                    = "dev"
endpoint_az_count      = 1
db_instance_class      = "db.t4g.micro"
db_multi_az            = false
db_backup_days         = 1
db_deletion_protection = false
monthly_budget_usd     = 30
container_insights     = false
