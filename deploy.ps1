# AWS App Runner deployment script for Windows
# Prerequisites: AWS CLI configured, Docker installed and running

$ErrorActionPreference = "Stop"

# Configuration
$AWS_REGION = if ($env:AWS_REGION) { $env:AWS_REGION } else { "ap-northeast-1" }
$APP_NAME = "simple-rag"
$ECR_REPO_NAME = "simple-rag"
$ACCOUNT_ID = aws sts get-caller-identity --query Account --output text
$ECR_URI = "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"

Write-Host "=== Simple RAG - App Runner Deployment ===" -ForegroundColor Cyan
Write-Host "Region: ${AWS_REGION}"
Write-Host "Account: ${ACCOUNT_ID}"
Write-Host ""

# Step 1: Create ECR repository (if not exists)
Write-Host "[1/5] Creating ECR repository..." -ForegroundColor Yellow
try {
    aws ecr describe-repositories --repository-names $ECR_REPO_NAME --region $AWS_REGION 2>$null | Out-Null
    Write-Host "  ECR repository already exists."
} catch {
    aws ecr create-repository --repository-name $ECR_REPO_NAME --region $AWS_REGION | Out-Null
    Write-Host "  ECR repository created."
}

# Step 2: Login to ECR
Write-Host "[2/5] Logging in to ECR..." -ForegroundColor Yellow
$password = aws ecr get-login-password --region $AWS_REGION
docker login --username AWS --password $password "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Step 3: Build Docker image
Write-Host "[3/5] Building Docker image..." -ForegroundColor Yellow
docker build --platform linux/amd64 -t "${ECR_REPO_NAME}:latest" .

# Step 4: Push to ECR
Write-Host "[4/5] Pushing to ECR..." -ForegroundColor Yellow
docker tag "${ECR_REPO_NAME}:latest" "${ECR_URI}:latest"
docker push "${ECR_URI}:latest"

# Step 5: Create or update App Runner service
Write-Host "[5/5] Deploying to App Runner..." -ForegroundColor Yellow

$services = aws apprunner list-services --region $AWS_REGION --query "ServiceSummaryList[?ServiceName=='${APP_NAME}'].ServiceArn" --output text
$SERVICE_ARN = if ($services -and $services -ne "None") { $services } else { $null }

if (-not $SERVICE_ARN) {
    Write-Host "  Creating new App Runner service..." -ForegroundColor Green

    # Create IAM role for ECR access (if not exists)
    $ROLE_NAME = "AppRunnerECRAccessRole"
    try {
        $ROLE_ARN = aws iam get-role --role-name $ROLE_NAME --query 'Role.Arn' --output text 2>$null
    } catch {
        $ROLE_ARN = $null
    }

    if (-not $ROLE_ARN -or $ROLE_ARN -eq "None") {
        Write-Host "  Creating IAM role for App Runner ECR access..."

        $trustPolicy = @'
{
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "build.apprunner.amazonaws.com"},
        "Action": "sts:AssumeRole"
    }]
}
'@
        $trustPolicy | Out-File -FilePath "trust-policy.json" -Encoding utf8
        aws iam create-role --role-name $ROLE_NAME --assume-role-policy-document file://trust-policy.json | Out-Null
        aws iam attach-role-policy --role-name $ROLE_NAME --policy-arn "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess" | Out-Null
        Remove-Item "trust-policy.json"

        Write-Host "  Waiting for role propagation..."
        Start-Sleep -Seconds 10
        $ROLE_ARN = aws iam get-role --role-name $ROLE_NAME --query 'Role.Arn' --output text
    }

    # Check ANTHROPIC_API_KEY
    if (-not $env:ANTHROPIC_API_KEY) {
        Write-Host ""
        Write-Host "WARNING: ANTHROPIC_API_KEY environment variable is not set." -ForegroundColor Red
        Write-Host "Set it before running: `$env:ANTHROPIC_API_KEY = 'sk-ant-xxxxx'" -ForegroundColor Red
        Write-Host "The service will be created but chat will not work without the key." -ForegroundColor Red
        Write-Host ""
    }

    $ANTHROPIC_KEY = if ($env:ANTHROPIC_API_KEY) { $env:ANTHROPIC_API_KEY } else { "PLACEHOLDER" }

    # Create App Runner service config
    $sourceConfig = @"
{
    "AuthenticationConfiguration": {
        "AccessRoleArn": "${ROLE_ARN}"
    },
    "ImageRepository": {
        "ImageIdentifier": "${ECR_URI}:latest",
        "ImageRepositoryType": "ECR",
        "ImageConfiguration": {
            "Port": "8080",
            "RuntimeEnvironmentVariables": {
                "ANTHROPIC_API_KEY": "${ANTHROPIC_KEY}"
            }
        }
    }
}
"@
    $sourceConfig | Out-File -FilePath "source-config.json" -Encoding utf8

    $instanceConfig = '{"Cpu": "1024", "Memory": "2048"}'
    $instanceConfig | Out-File -FilePath "instance-config.json" -Encoding utf8

    aws apprunner create-service `
        --region $AWS_REGION `
        --service-name $APP_NAME `
        --source-configuration file://source-config.json `
        --instance-configuration file://instance-config.json

    Remove-Item "source-config.json"
    Remove-Item "instance-config.json"

    Write-Host ""
    Write-Host "Service is being created. It may take 3-5 minutes." -ForegroundColor Green
} else {
    Write-Host "  Updating existing App Runner service..." -ForegroundColor Green
    aws apprunner start-deployment --region $AWS_REGION --service-arn $SERVICE_ARN
}

Write-Host ""
Write-Host "=== Deployment initiated ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "To get your service URL, run:" -ForegroundColor Yellow
Write-Host '  $arn = aws apprunner list-services --region '${AWS_REGION}' --query "ServiceSummaryList[?ServiceName==''simple-rag''].ServiceArn" --output text'
Write-Host '  aws apprunner describe-service --service-arn $arn --region '${AWS_REGION}' --query "Service.ServiceUrl" --output text'
