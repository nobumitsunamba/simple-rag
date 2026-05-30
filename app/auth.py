"""Authentication module using Amazon Cognito."""

import os
import time
import hmac
import hashlib
import base64

import boto3
from botocore.exceptions import ClientError


COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "ap-northeast-1_xVcjer1Dr")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "2ll9e48rfu5q5ias8ttqhn3p5d")
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")


def _get_cognito_client():
    return boto3.client("cognito-idp", region_name=AWS_REGION)


def sign_up(email: str, password: str) -> dict:
    """Register a new user."""
    client = _get_cognito_client()
    try:
        response = client.sign_up(
            ClientId=COGNITO_CLIENT_ID,
            Username=email,
            Password=password,
            UserAttributes=[{"Name": "email", "Value": email}],
        )
        return {"message": "確認コードをメールに送信しました。", "user_sub": response["UserSub"]}
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "UsernameExistsException":
            raise ValueError("このメールアドレスは既に登録されています。")
        elif code == "InvalidPasswordException":
            raise ValueError("パスワードは8文字以上で、大文字・小文字・数字を含めてください。")
        else:
            raise ValueError(f"登録エラー: {e.response['Error']['Message']}")


def confirm_sign_up(email: str, code: str) -> dict:
    """Confirm user registration with verification code."""
    client = _get_cognito_client()
    try:
        client.confirm_sign_up(
            ClientId=COGNITO_CLIENT_ID,
            Username=email,
            ConfirmationCode=code,
        )
        return {"message": "アカウントが確認されました。ログインしてください。"}
    except ClientError as e:
        code_err = e.response["Error"]["Code"]
        if code_err == "CodeMismatchException":
            raise ValueError("確認コードが正しくありません。")
        elif code_err == "ExpiredCodeException":
            raise ValueError("確認コードの有効期限が切れています。")
        else:
            raise ValueError(f"確認エラー: {e.response['Error']['Message']}")


def sign_in(email: str, password: str) -> dict:
    """Authenticate a user and return tokens."""
    client = _get_cognito_client()
    try:
        response = client.initiate_auth(
            ClientId=COGNITO_CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": email,
                "PASSWORD": password,
            },
        )
        auth_result = response["AuthenticationResult"]
        return {
            "access_token": auth_result["AccessToken"],
            "id_token": auth_result["IdToken"],
            "refresh_token": auth_result["RefreshToken"],
            "expires_in": auth_result["ExpiresIn"],
        }
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NotAuthorizedException":
            raise ValueError("メールアドレスまたはパスワードが正しくありません。")
        elif code == "UserNotConfirmedException":
            raise ValueError("アカウントが未確認です。メールの確認コードを入力してください。")
        elif code == "UserNotFoundException":
            raise ValueError("このメールアドレスは登録されていません。")
        else:
            raise ValueError(f"ログインエラー: {e.response['Error']['Message']}")


def verify_token(access_token: str) -> dict | None:
    """Verify an access token and return user info."""
    client = _get_cognito_client()
    try:
        response = client.get_user(AccessToken=access_token)
        attrs = {a["Name"]: a["Value"] for a in response["UserAttributes"]}
        return {
            "username": response["Username"],
            "email": attrs.get("email", ""),
        }
    except ClientError:
        return None
