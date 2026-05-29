# AWS セットアップ手順

GitHub Actions から ECS Express Mode にデプロイするための事前準備です。

## 1. ECR リポジトリの作成

```powershell
aws ecr create-repository --repository-name simple-rag --region ap-northeast-1
```

## 2. ECS 用 IAM ロールの作成

### Task Execution Role

```powershell
aws iam create-role --role-name ecsTaskExecutionRole --assume-role-policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"ecs-tasks.amazonaws.com\"},\"Action\":\"sts:AssumeRole\"}]}'

aws iam attach-role-policy --role-name ecsTaskExecutionRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
```

### Infrastructure Role

```powershell
aws iam create-role --role-name ecsInfrastructureRoleForExpressServices --assume-role-policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"AllowAccessInfrastructureForECSExpressServices\",\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"ecs.amazonaws.com\"},\"Action\":\"sts:AssumeRole\"}]}'

aws iam attach-role-policy --role-name ecsInfrastructureRoleForExpressServices --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices
```

## 3. GitHub Actions 用 OIDC IAM ロールの作成

### 3-1. GitHub OIDC プロバイダーの登録（初回のみ）

```powershell
aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com --client-id-list sts.amazonaws.com --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

### 3-2. GitHub Actions 用ロールの作成

以下の内容で `github-actions-trust-policy.json` を作成：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::ff46203:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:nobumitsunamba/simple-rag:*"
        }
      }
    }
  ]
}
```

```powershell
aws iam create-role --role-name GitHubActionsRole-SimpleRAG --assume-role-policy-document file://github-actions-trust-policy.json
```

### 3-3. ロールにポリシーをアタッチ

```powershell
aws iam attach-role-policy --role-name GitHubActionsRole-SimpleRAG --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser

aws iam put-role-policy --role-name GitHubActionsRole-SimpleRAG --policy-name ECSExpressDeploy --policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"ecs:*\",\"iam:PassRole\",\"elasticloadbalancing:*\",\"ec2:Describe*\",\"logs:*\"],\"Resource\":\"*\"}]}'
```

## 4. GitHub リポジトリの Secrets 設定

GitHub リポジトリの Settings > Secrets and variables > Actions で以下を追加：

| Secret 名 | 値 |
|-----------|-----|
| `AWS_ROLE_ARN` | `arn:aws:iam::ff46203:role/GitHubActionsRole-SimpleRAG` |
| `AWS_ACCOUNT_ID` | `ff46203` |
| `ANTHROPIC_API_KEY` | あなたの Anthropic API キー |

## 5. デプロイ

上記が完了したら、コードを `main` ブランチにプッシュすれば自動デプロイされます。

デプロイ完了後、以下の形式のURLでアクセスできます：
```
https://simple-rag.ecs.ap-northeast-1.on.aws/
```
