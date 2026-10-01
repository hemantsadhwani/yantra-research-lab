#!/usr/bin/env bash
# One-time account setup for the yantra dev box (ap-south-1), run with a TEMPORARY admin profile.
# Creates the box role, launcher user, alarm service-linked role and GPU quota requests that an
# admin would otherwise set up by hand in the console. Idempotent: re-running skips anything that
# already exists.
#
#   bash deploy/ec2/setup_account.sh            # role + instance profile (Bedrock + S3 data), launcher user + CLI profile,
#                                               # alarm service-linked role, GPU quota requests, Bedrock check
#
# Settings (env): ADMIN_PROFILE=yantra-admin LAUNCHER_PROFILE=yantra-launcher REGION=ap-south-1 QUOTA=8
# Afterwards delete the temporary admin user; day-to-day work uses only LAUNCHER_PROFILE (launch.sh).
set -euo pipefail

ADMIN_PROFILE="${ADMIN_PROFILE:-yantra-admin}"
LAUNCHER_PROFILE="${LAUNCHER_PROFILE:-yantra-launcher}"
REGION="${REGION:-ap-south-1}"
QUOTA="${QUOTA:-8}"
ROLE=yantra-dev-bedrock
LAUNCHER_USER=claude-dev-launcher
DATA_BUCKET="${DATA_BUCKET:-yantra-research-lab-data}"
HERE="$(cd "$(dirname "$0")" && pwd)"

aws_() { aws --profile "$ADMIN_PROFILE" --region "$REGION" "$@"; }

echo "== identity: $(aws_ sts get-caller-identity --query Arn --output text)"

echo "== role $ROLE"
if aws_ iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  echo "exists"
else
  aws_ iam create-role --role-name "$ROLE" --description "yantra dev box: Bedrock invoke + S3 data (corpus read, ml read/write)" \
    --tags Key=purpose,Value=dev-public-repos \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
    --query Role.Arn --output text
fi
aws_ iam put-role-policy --role-name "$ROLE" --policy-name bedrock-dev \
  --policy-document "file://$HERE/iam/bedrock-dev-role-policy.json"

echo "== S3 data access for the box: read yantra-corpus/*, read+write ml/* (no delete)"
loc=$(aws_ s3api get-bucket-location --bucket "$DATA_BUCKET" --query LocationConstraint --output text)
enc=$(aws_ s3api get-bucket-encryption --bucket "$DATA_BUCKET" \
        --query 'ServerSideEncryptionConfiguration.Rules[0].ApplyServerSideEncryptionByDefault.SSEAlgorithm' \
        --output text 2>/dev/null || echo none)
echo "bucket $DATA_BUCKET: region $loc, default encryption $enc"
[[ "$enc" == "aws:kms" ]] && echo "WARN: SSE-KMS bucket; the role also needs kms:Decrypt/GenerateDataKey on that key"
aws_ iam put-role-policy --role-name "$ROLE" --policy-name s3-data \
  --policy-document "file://$HERE/iam/dev-box-s3-policy.json"
role_arn=$(aws_ iam get-role --role-name "$ROLE" --query Role.Arn --output text)
sim() {  # sim <action> <object-or-bucket arn> -> allowed | implicitDeny | explicitDeny
  aws_ iam simulate-principal-policy --policy-source-arn "$role_arn" --action-names "$1" \
    --resource-arns "$2" --query 'EvaluationResults[0].EvalDecision' --output text
}
B="arn:aws:s3:::$DATA_BUCKET"
for check in "s3:GetObject $B/yantra-corpus/parsed/x.json allowed" \
             "s3:PutObject $B/yantra-corpus/raw/x.pdf implicitDeny" \
             "s3:PutObject $B/ml/models/x allowed" \
             "s3:DeleteObject $B/ml/models/x implicitDeny" \
             "s3:GetObject $B/other/x implicitDeny"; do
  read -r act res want <<<"$check"
  got=$(sim "$act" "$res")
  [[ "$got" == "$want" ]] && mark=ok || mark=MISMATCH
  echo "  $mark  $act ${res#"$B"/} -> $got"
done

echo "== instance profile $ROLE"
if ! aws_ iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
  aws_ iam create-instance-profile --instance-profile-name "$ROLE" >/dev/null
fi
if [[ -z "$(aws_ iam get-instance-profile --instance-profile-name "$ROLE" --query 'InstanceProfile.Roles[].RoleName' --output text)" ]]; then
  aws_ iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
fi
echo "ok"

echo "== service-linked role for the idle-stop alarm"
aws_ iam create-service-linked-role --aws-service-name events.amazonaws.com >/dev/null 2>&1 && echo "created" || echo "exists"

echo "== launcher user $LAUNCHER_USER"
if aws_ iam get-user --user-name "$LAUNCHER_USER" >/dev/null 2>&1; then
  echo "exists"
else
  aws_ iam create-user --user-name "$LAUNCHER_USER" --tags Key=purpose,Value=dev-public-repos >/dev/null
  echo "created"
fi
# Managed, not inline: the policy is over IAM's 2048-char inline-user limit.
acct=$(aws_ sts get-caller-identity --query Account --output text)
parn="arn:aws:iam::$acct:policy/yantra-dev-launcher"
if aws_ iam get-policy --policy-arn "$parn" >/dev/null 2>&1; then
  for v in $(aws_ iam list-policy-versions --policy-arn "$parn" --query 'Versions[?!IsDefaultVersion].VersionId' --output text); do
    aws_ iam delete-policy-version --policy-arn "$parn" --version-id "$v"
  done
  aws_ iam create-policy-version --policy-arn "$parn" --set-as-default \
    --policy-document "file://$HERE/iam/launcher-policy.json" >/dev/null
else
  aws_ iam create-policy --policy-name yantra-dev-launcher --tags Key=purpose,Value=dev-public-repos \
    --policy-document "file://$HERE/iam/launcher-policy.json" >/dev/null
fi
aws_ iam attach-user-policy --user-name "$LAUNCHER_USER" --policy-arn "$parn"

echo "== CLI profile $LAUNCHER_PROFILE"
if aws configure list-profiles | grep -qx "$LAUNCHER_PROFILE"; then
  echo "exists (key not rotated)"
else
  # The key goes straight into ~/.aws/credentials; it is never printed.
  read -r kid secret < <(aws_ iam create-access-key --user-name "$LAUNCHER_USER" \
                           --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)
  aws configure set aws_access_key_id "$kid" --profile "$LAUNCHER_PROFILE"
  aws configure set aws_secret_access_key "$secret" --profile "$LAUNCHER_PROFILE"
  aws configure set region "$REGION" --profile "$LAUNCHER_PROFILE"
  aws configure set output json --profile "$LAUNCHER_PROFILE"
  unset kid secret
  echo "written"
fi

echo "== GPU vCPU quotas (want >= $QUOTA)"
pending=$(aws_ service-quotas list-requested-service-quota-change-history --service-code ec2 \
            --query 'RequestedQuotas[?Status==`PENDING` || Status==`CASE_OPENED`].QuotaCode' --output text)
for code in L-DB2E81BA L-3819A6DF; do   # G/VT on-demand, G/VT spot
  have=$(aws_ service-quotas get-service-quota --service-code ec2 --quota-code "$code" --query Quota.Value --output text)
  if [[ "${have%.*}" -ge "$QUOTA" ]]; then
    echo "$code: $have (enough)"
  elif [[ " $pending " == *" $code "* ]]; then
    echo "$code: $have (request already pending)"
  else
    echo "$code: $have -> requesting $QUOTA: $(aws_ service-quotas request-service-quota-increase --service-code ec2 \
      --quota-code "$code" --desired-value "$QUOTA" --query RequestedQuota.Status --output text)"
  fi
done

echo "== Bedrock Claude Haiku 4.5 in $REGION"
aws_ bedrock list-inference-profiles \
  --query 'inferenceProfileSummaries[?contains(inferenceProfileId,`claude-haiku-4-5`)].inferenceProfileId' --output text
