"""Customer-managed-key boundary.

This module intentionally performs real AWS KMS envelope-key generation when
enabled; it never treats a key ARN field as encryption by itself.
"""

from dataclasses import dataclass
from typing import Optional
import boto3
from app.core.config import settings
from botocore.exceptions import BotoCoreError


@dataclass(frozen=True)
class EncryptedPayload:
    ciphertext: bytes
    encrypted_data_key: bytes
    key_arn: str


def validate_tenant_key_region(key_arn: str, data_region: str) -> None:
    """Reject a CMK that can violate the tenant's declared residency."""
    if not key_arn.startswith("arn:aws:kms:"):
        raise ValueError("kmsKeyArn must be an AWS KMS ARN")
    region = key_arn.split(":", 4)[3]
    allowed = {"eu": region.startswith("eu-"), "us": region.startswith(("us-", "ca-"))}
    if data_region not in allowed:
        raise ValueError("Unsupported tenant data region")
    if not allowed[data_region]:
        raise ValueError("KMS key region does not match tenant data region")


def encrypt_payload(payload: bytes, key_arn: Optional[str]) -> EncryptedPayload:
    if not key_arn:
        if settings.KMS_REQUIRED_FOR_TENANT_DATA:
            raise RuntimeError("Tenant KMS key is required")
        raise ValueError("A KMS key ARN is required for envelope encryption")
    try:
        kms = boto3.client("kms", region_name=settings.AWS_REGION)
        response = kms.generate_data_key(KeyId=key_arn, KeySpec="AES_256")
    except BotoCoreError as exc:
        raise RuntimeError("KMS data-key generation failed") from exc
    plaintext_key = response["Plaintext"]
    encrypted_key = response["CiphertextBlob"]
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = __import__("os").urandom(12)
    ciphertext = nonce + AESGCM(plaintext_key).encrypt(nonce, payload, None)
    return EncryptedPayload(ciphertext, encrypted_key, key_arn)
