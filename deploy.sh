#!/bin/bash
# AWS App Runner deployment script
# Prerequisites: AWS CLI configured, Docker installed

set -e

# Configuration
AWS_REGION="${AWS_REGION:-ap-northeast-1}"
APP_NAME="simple-rag"
ECR_REPO_NAME="simple-rag"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"

echo "=== Simple RAG - App Runner Deployment ==="
echo "Region: ${AWS_REGION}"
echo "Account: ${ACCOUNT_ID}"
echo ""

# Step 1: Create ECR repository (if not exists)
echo "[1/5] Creating ECR repository..."
aws ecr describe-repositories --repository-names ${ECR_REPO_NAME} --region ${AWS_REGION} 2>/dev/null || \
    aws ecr create-repository --repository-name ${ECR_REPO_NAME} --region ${AWS_REGION}

# Step 2: Login to ECR
echo "[2/5] Logging in to ECR..."
aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_URI}

# Step 3: Build and push Docker image
echo "[3/5] Building Docker image..."
docker build --platform linux/amd64 -t ${ECR_REPO_NAME}:latest .

echo "[4/5] Pushing to ECR..."
docker tag ${ECR_REPO_NAME}:latest ${ECR_URI}:latest
docker push ${ECR_URI}:latest

# Step 4: Create or update App Runner service
echo "[5/5] Deploying to App Runner..."

# Check if service exists
SERVICE_ARN=$(aws apprunner list-services --region ${AWS_REGION} \
    --query "ServiceSummaryList[?ServiceName=='${APP_NAME}'].ServiceArn" \
    --output text 2>/dev/null)

if [ -z "$SERVICE_ARN" ] || [ "$SERVICE_ARN" = "None" ]; then
    echo "Creating new App Runner service..."
    
    # Create App Runner access role for ECR (if not exists)
    ROLE_NAME="AppRunnerECRAccessRole"
    ROLE_ARN=$(aws iam get-role --role-name ${ROLE_NAME} --query 'Role.Arn' --output text 2>/dev/null || true)
    
    if [ -z "$ROLE_ARN" ] || [ "$ROLE_ARN" = "None" ]; then
        echo "Creating IAM role for App Runner ECR access..."
        aws iam create-role \
            --role-name ${ROLE_NAME} \
            --assume-role-policy-document '{
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"Service": "build.apprunner.amazonaws.com"},
                    "Action": "sts:AssumeRole"
                }]
            }'
        
        aws iam attach-role-policy \
            --role-name ${ROLE_NAME} \
            --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess
        
        echo "Waiting for role propagation..."
        sleep 10
        ROLE_ARN=$(aws iam get-role --role-name ${ROLE_NAME} --query 'Role.Arn' --output text)
    fi

    # Create the service
    aws apprunner create-service \
        --region ${AWS_REGION} \
        --service-name ${APP_NAME} \
        --source-configuration "{
            \"AuthenticationConfiguration\": {
                \"AccessRoleArn\": \"${ROLE_ARN}\"
            },
            \"ImageRepository\": {
                \"ImageIdentifier\": \"${ECR_URI}:latest\",
                \"ImageRepositoryType\": \"ECR\",
                \"ImageConfiguration\": {
                    \"Port\": \"8080\",
                    \"RuntimeEnvironmentVariables\": {
                        \"ANTHROPIC_API_KEY\": \"${ANTHROPIC_API_KEY}\"
                    }
                }
            }
        }" \
        --instance-configuration "{
            \"Cpu\": \"1024\",
            \"Memory\": \"2048\"
        }"
    
    echo ""
    echo "Service is being created. It may take a few minutes."
    echo "Check status with: aws apprunner list-services --region ${AWS_REGION}"
else
    echo "Updating existing App Runner service..."
    aws apprunner start-deployment \
        --region ${AWS_REGION} \
        --service-arn ${SERVICE_ARN}
fi

echo ""
echo "=== Deployment initiated ==="
echo "Run the following to get your service URL:"
echo "  aws apprunner describe-service --service-arn \$(aws apprunner list-services --region ${AWS_REGION} --query \"ServiceSummaryList[?ServiceName=='${APP_NAME}'].ServiceArn\" --output text) --region ${AWS_REGION} --query 'Service.ServiceUrl' --output text"
