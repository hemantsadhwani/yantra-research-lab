output "url" {
  description = "The public page."
  value       = "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "rebuild_now" {
  value = "aws lambda invoke --function-name ${aws_lambda_function.rebuild.function_name} --profile ${var.aws_profile} --region ${var.region} out.json"
}
