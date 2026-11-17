#!/usr/bin/env bash
# Build the static site and publish it to the S3 bucket behind CloudFront (infra/track_record).
#
#   AWS_PROFILE=agentic bash frontend/deploy_aws.sh
#
# The bucket and distribution come from Terraform outputs. data/track_record.json is owned by
# the track-record Lambda and is never uploaded or deleted from here.
set -euo pipefail
cd "$(dirname "$0")"
TF_DIR=../infra/track_record
TF=${TF:-terraform}
BUCKET=$("$TF" -chdir="$TF_DIR" output -raw site_bucket)
DIST=$("$TF" -chdir="$TF_DIR" output -raw distribution_id)
REGION=${AWS_REGION:-ap-south-1}

STATIC_EXPORT=1 NEXT_TELEMETRY_DISABLED=1 npm run build
rm -f out/data/track_record.json          # never ship a local copy over the Lambda's file

# Hashed assets: cache for a year. Everything else (HTML, data, the record page): 5 minutes.
aws s3 sync out/_next "s3://$BUCKET/_next" --region "$REGION" --delete \
  --cache-control "public, max-age=31536000, immutable"
aws s3 sync out "s3://$BUCKET" --region "$REGION" --delete \
  --exclude "_next/*" --exclude "data/track_record.json" \
  --cache-control "public, max-age=300"

aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/*" \
  --query "Invalidation.Id" --output text
echo "published: https://$("$TF" -chdir="$TF_DIR" output -raw url | sed 's#https://##')"
