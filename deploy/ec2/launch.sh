#!/usr/bin/env bash
# Launch and manage the yantra dev box (ap-south-1) with the least-privilege launcher profile.
# Runs from any Linux/macOS shell with AWS CLI v2 (e.g. nifty_dev). Touches ONLY resources tagged
# purpose=dev-public-repos; the IAM policy (iam/launcher-policy.json) enforces the same.
#
#   bash deploy/ec2/launch.sh preflight            # identity, quota, type offerings, role, AMI   (free)
#   bash deploy/ec2/launch.sh quota [N]            # request G/VT on-demand vCPU quota (default 8)  (free)
#   bash deploy/ec2/launch.sh plan                 # print exactly what `launch` would create        (free)
#   bash deploy/ec2/launch.sh launch --yes         # key pair + SG + instance + idle alarm           (BILLS)
#   bash deploy/ec2/launch.sh status | ssh | stop | start
#   bash deploy/ec2/launch.sh resize <type> --yes  # stop, change type, start                        (BILLS)
#   bash deploy/ec2/launch.sh terminate --yes      # delete the box and its disk                     (irreversible)
#
# Settings (env): PROFILE=yantra-launcher REGION=ap-south-1 TYPE=g5.xlarge MARKET=ondemand|spot
#                 DISK_GB=200 NAME=yantra_dev EXTRA_SSH_CIDR=<your home IP>/32
set -euo pipefail

PROFILE="${PROFILE:-yantra-launcher}"
REGION="${REGION:-ap-south-1}"
TYPE="${TYPE:-g5.xlarge}"
MARKET="${MARKET:-ondemand}"
DISK_GB="${DISK_GB:-200}"
NAME="${NAME:-yantra_dev}"
ROLE="${ROLE:-yantra-dev-bedrock}"
KEY_NAME="${KEY_NAME:-yantra-dev}"
SG_NAME="${SG_NAME:-yantra-dev-ssh}"
TAG_KEY=purpose; TAG_VAL=dev-public-repos
STATE_DIR="$HOME/.yantra-dev"; mkdir -p "$STATE_DIR"
KEY_FILE="$HOME/.ssh/${KEY_NAME}.pem"

aws_() { aws --profile "$PROFILE" --region "$REGION" "$@"; }
die()  { echo "ERROR: $*" >&2; exit 1; }
need_yes() { [[ " $* " == *" --yes "* ]] || die "this step costs money or is irreversible; re-run with --yes after the owner agrees"; }

tagspec() {  # tagspec <resource-type>
  echo "ResourceType=$1,Tags=[{Key=$TAG_KEY,Value=$TAG_VAL},{Key=Name,Value=$NAME}]"
}

ami_for_type() {
  case "$1" in
    g*|p*)
      local p="/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-24.04/latest/ami-id"
      aws_ ssm get-parameter --name "$p" --query Parameter.Value --output text 2>/dev/null \
        || aws_ ec2 describe-images --owners amazon \
             --filters "Name=name,Values=Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 24.04)*" "Name=state,Values=available" \
             --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text ;;
    t4g*|c7g*|m7g*|c8g*)
      aws_ ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id \
        --query Parameter.Value --output text ;;
    *)
      aws_ ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
        --query Parameter.Value --output text ;;
  esac
}

instance_id() {
  aws_ ec2 describe-instances \
    --filters "Name=tag:$TAG_KEY,Values=$TAG_VAL" "Name=tag:Name,Values=$NAME" \
              "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[0].InstanceId' --output text | awk '{print $1}' | sed 's/None//'
}

public_ip() { aws_ ec2 describe-instances --instance-ids "$1" --query 'Reservations[0].Instances[0].PublicIpAddress' --output text; }

preflight() {
  echo "== identity";  aws_ sts get-caller-identity --output text
  echo "== G/VT on-demand vCPU quota (L-DB2E81BA)"
  aws_ service-quotas get-service-quota --service-code ec2 --quota-code L-DB2E81BA --query Quota.Value --output text || true
  echo "== G/VT spot vCPU quota (L-3819A6DF)"
  aws_ service-quotas get-service-quota --service-code ec2 --quota-code L-3819A6DF --query Quota.Value --output text || true
  echo "== AZs offering $TYPE"
  aws_ ec2 describe-instance-type-offerings --location-type availability-zone \
    --filters "Name=instance-type,Values=$TYPE" --query 'InstanceTypeOfferings[].Location' --output text
  echo "== role $ROLE";  aws --profile "$PROFILE" iam get-instance-profile --instance-profile-name "$ROLE" \
    --query 'InstanceProfile.Roles[0].RoleName' --output text || echo "missing: create role $ROLE for EC2 (console)"
  echo "== AMI for $TYPE: $(ami_for_type "$TYPE")"
  echo "== existing dev box: $(instance_id || true)"
}

quota() {
  local n="${1:-8}"
  aws_ service-quotas request-service-quota-increase --service-code ec2 --quota-code L-DB2E81BA --desired-value "$n" \
    --query 'RequestedQuota.Status' --output text
  echo "requested $n vCPUs for G/VT on-demand in $REGION; approval can take hours"
}

pick_subnet() {
  local az
  for az in $(aws_ ec2 describe-instance-type-offerings --location-type availability-zone \
                --filters "Name=instance-type,Values=$TYPE" --query 'InstanceTypeOfferings[].Location' --output text); do
    local s; s=$(aws_ ec2 describe-subnets --filters "Name=default-for-az,Values=true" "Name=availability-zone,Values=$az" \
                   --query 'Subnets[0].SubnetId' --output text)
    [[ "$s" != "None" && -n "$s" ]] && { echo "$s"; return; }
  done
  die "no default subnet in an AZ offering $TYPE"
}

plan() {
  local ami subnet myip; ami=$(ami_for_type "$TYPE"); subnet=$(pick_subnet)
  myip=$(curl -fsS https://checkip.amazonaws.com | tr -d '\n')
  cat <<EOF
PLAN (nothing created yet)
  instance   $NAME  type $TYPE  market $MARKET  region $REGION  subnet $subnet
  ami        $ami
  disk       ${DISK_GB} GB gp3, deleted on terminate
  role       $ROLE (Bedrock invoke only)
  key pair   $KEY_NAME -> $KEY_FILE
  ssh from   $myip/32 ${EXTRA_SSH_CIDR:+and $EXTRA_SSH_CIDR}
  tags       $TAG_KEY=$TAG_VAL, Name=$NAME
  idle stop  CloudWatch alarm yantra-dev-idle-stop: CPU < 2% for 60 min -> stop
  cost       starts billing at launch; see HANDOVER.md section 1 for the hourly rate
EOF
}

launch() {
  need_yes "$@"
  [[ -n "$(instance_id)" ]] && die "a dev box named $NAME already exists: $(instance_id). Use start/status."
  plan
  local ami subnet vpc myip sg root
  ami=$(ami_for_type "$TYPE"); subnet=$(pick_subnet)
  vpc=$(aws_ ec2 describe-subnets --subnet-ids "$subnet" --query 'Subnets[0].VpcId' --output text)
  myip=$(curl -fsS https://checkip.amazonaws.com | tr -d '\n')
  root=$(aws_ ec2 describe-images --image-ids "$ami" --query 'Images[0].RootDeviceName' --output text)

  if [[ ! -f "$KEY_FILE" ]]; then
    mkdir -p "$HOME/.ssh"
    aws_ ec2 create-key-pair --key-name "$KEY_NAME" --key-type ed25519 \
      --tag-specifications "$(tagspec key-pair)" --query KeyMaterial --output text > "$KEY_FILE"
    chmod 400 "$KEY_FILE"
  fi

  sg=$(aws_ ec2 describe-security-groups --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$vpc" \
         --query 'SecurityGroups[0].GroupId' --output text)
  if [[ "$sg" == "None" || -z "$sg" ]]; then
    sg=$(aws_ ec2 create-security-group --group-name "$SG_NAME" --description "yantra dev box: SSH from owner IPs only" \
           --vpc-id "$vpc" --tag-specifications "$(tagspec security-group)" --query GroupId --output text)
    aws_ ec2 authorize-security-group-ingress --group-id "$sg" --protocol tcp --port 22 --cidr "$myip/32" >/dev/null
    [[ -n "${EXTRA_SSH_CIDR:-}" ]] && aws_ ec2 authorize-security-group-ingress --group-id "$sg" --protocol tcp --port 22 --cidr "$EXTRA_SSH_CIDR" >/dev/null
  fi

  local market=()
  [[ "$MARKET" == "spot" ]] && market=(--instance-market-options 'MarketType=spot,SpotOptions={SpotInstanceType=persistent,InstanceInterruptionBehavior=stop}')

  local id
  id=$(aws_ ec2 run-instances --image-id "$ami" --instance-type "$TYPE" --key-name "$KEY_NAME" \
        --subnet-id "$subnet" --security-group-ids "$sg" --iam-instance-profile "Name=$ROLE" \
        --metadata-options HttpTokens=required \
        --block-device-mappings "[{\"DeviceName\":\"$root\",\"Ebs\":{\"VolumeSize\":$DISK_GB,\"VolumeType\":\"gp3\",\"DeleteOnTermination\":true}}]" \
        --tag-specifications "$(tagspec instance)" "$(tagspec volume)" \
        ${market[@]+"${market[@]}"} --query 'Instances[0].InstanceId' --output text)
  echo "$id" > "$STATE_DIR/instance_id"
  echo "launched $id; waiting for status checks..."
  aws_ ec2 wait instance-status-ok --instance-ids "$id"

  aws_ cloudwatch put-metric-alarm --alarm-name yantra-dev-idle-stop \
    --namespace AWS/EC2 --metric-name CPUUtilization --dimensions "Name=InstanceId,Value=$id" \
    --statistic Average --period 300 --evaluation-periods 12 --threshold 2 --comparison-operator LessThanThreshold \
    --alarm-actions "arn:aws:automate:$REGION:ec2:stop" --treat-missing-data notBreaching \
    || echo "WARN: idle alarm not created (first time needs a service-linked role; create it once in the console)"

  echo "ready: ssh -i $KEY_FILE ubuntu@$(public_ip "$id")"
}

status()   { local id; id=$(instance_id); [[ -z "$id" ]] && { echo "no dev box"; return; }
             aws_ ec2 describe-instances --instance-ids "$id" \
               --query 'Reservations[0].Instances[0].[InstanceId,InstanceType,State.Name,PublicIpAddress]' --output text; }
do_ssh()   { local id; id=$(instance_id); exec ssh -i "$KEY_FILE" -o StrictHostKeyChecking=accept-new "ubuntu@$(public_ip "$id")"; }
stop()     { local id; id=$(instance_id); aws_ ec2 stop-instances --instance-ids "$id" --query 'StoppingInstances[0].CurrentState.Name' --output text; }
start()    { local id; id=$(instance_id); aws_ ec2 start-instances --instance-ids "$id" --query 'StartingInstances[0].CurrentState.Name' --output text
             aws_ ec2 wait instance-running --instance-ids "$id"; echo "ssh -i $KEY_FILE ubuntu@$(public_ip "$id")  (public IP changes on each start)"; }
resize()   { local new="${1:?usage: resize <type> --yes}"; shift; need_yes "$@"; local id; id=$(instance_id)
             aws_ ec2 stop-instances --instance-ids "$id" >/dev/null; aws_ ec2 wait instance-stopped --instance-ids "$id"
             aws_ ec2 modify-instance-attribute --instance-id "$id" --instance-type "{\"Value\":\"$new\"}"
             echo "type is now $new (a GPU AMI still boots on CPU types, just without CUDA)"; start; }
terminate(){ need_yes "$@"; local id; id=$(instance_id)
             aws_ ec2 terminate-instances --instance-ids "$id" --query 'TerminatingInstances[0].CurrentState.Name' --output text
             aws_ cloudwatch delete-alarms --alarm-names yantra-dev-idle-stop || true; rm -f "$STATE_DIR/instance_id"; }

cmd="${1:-help}"; shift || true
case "$cmd" in
  preflight) preflight ;;
  quota)     quota "${1:-8}" ;;
  plan)      plan ;;
  launch)    launch "$@" ;;
  status)    status ;;
  ssh)       do_ssh ;;
  stop)      stop ;;
  start)     start ;;
  resize)    resize "$@" ;;
  terminate) terminate "$@" ;;
  *)         sed -n '2,16p' "$0" ;;
esac
