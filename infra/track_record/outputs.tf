output "url" {
  description = "The public site (the track record is at /track-record/)."
  value       = "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "site_bucket" {
  description = "Where frontend/deploy_aws.sh syncs the static site."
  value       = aws_s3_bucket.site.id
}

output "distribution_id" {
  value = aws_cloudfront_distribution.site.id
}

output "rebuild_now" {
  value = "aws lambda invoke --function-name ${aws_lambda_function.rebuild.function_name} --profile ${var.aws_profile} --region ${var.region} out.json"
}
