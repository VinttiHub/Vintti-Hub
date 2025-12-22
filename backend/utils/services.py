import logging
import os

import boto3
import openai
from affinda import AffindaAPI, TokenCredential

s3_client = None
S3_BUCKET = None
affinda_client = None
WORKSPACE_ID = None
DOC_TYPE_ID = None


def init_services():
    """
    Initialize external clients (OpenAI, Affinda, AWS S3) after the environment
    variables have been loaded. Safe to call multiple times.
    """
    global s3_client, S3_BUCKET, affinda_client, WORKSPACE_ID, DOC_TYPE_ID

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if openai_api_key:
        openai.api_key = openai_api_key

    WORKSPACE_ID = os.getenv('AFFINDA_WORKSPACE_ID')
    DOC_TYPE_ID = os.getenv('AFFINDA_DOCUMENT_TYPE_ID')

    affinda_key = os.getenv('AFFINDA_API_KEY')
    affinda_client = None
    if affinda_key:
        try:
            affinda_client = AffindaAPI(
                credential=TokenCredential(token=affinda_key)
            )
        except Exception:
            logging.exception("❌ Failed to initialize Affinda client")

    s3_client = boto3.client(
        's3',
        region_name=os.getenv('AWS_REGION'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
    )
    S3_BUCKET = os.getenv('S3_BUCKET_NAME')


__all__ = [
    "init_services",
    "s3_client",
    "S3_BUCKET",
    "affinda_client",
    "WORKSPACE_ID",
    "DOC_TYPE_ID",
]
