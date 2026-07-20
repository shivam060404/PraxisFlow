"""
Encryption Module for PraxisFlow
Envelope encryption with per-tenant keys, field-level encryption for PII.
"""

import os
import base64
import logging
from typing import Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class EncryptedData:
    """Encrypted payload with metadata."""
    ciphertext: bytes
    nonce: bytes
    key_id: str
    algorithm: str = "AES-256-GCM"
    associated_data: Optional[bytes] = None


class KeyManager:
    """Manages encryption keys with rotation support."""

    def __init__(self):
        self._keys: Dict[str, bytes] = {}
        self._current_key_id = "primary"
        self._key_versions: Dict[str, int] = {}

    def generate_key(self, key_id: str = None) -> Tuple[str, bytes]:
        """Generate a new 256-bit key."""
        import secrets
        key_id = key_id or f"key_{secrets.token_hex(8)}"
        key = secrets.token_bytes(32)  # 256 bits
        self._keys[key_id] = key
        self._key_versions[key_id] = self._key_versions.get(key_id, 0) + 1
        logger.info(f"Generated new encryption key: {key_id}")
        return key_id, key

    def get_key(self, key_id: str) -> Optional[bytes]:
        """Get key by ID."""
        return self._keys.get(key_id)

    def get_current_key(self) -> Tuple[str, bytes]:
        """Get current primary key."""
        key = self._keys.get(self._current_key_id)
        if not key:
            # Generate if not exists
            return self.generate_key(self._current_key_id)
        return self._current_key_id, key

    def set_current_key(self, key_id: str):
        """Set current key for new encryptions."""
        if key_id not in self._keys:
            raise ValueError(f"Key {key_id} does not exist")
        self._current_key_id = key_id
        logger.info(f"Set current encryption key to: {key_id}")

    def rotate_key(self, new_key_id: str = None) -> str:
        """Rotate to a new key."""
        old_key_id = self._current_key_id
        new_key_id, _ = self.generate_key(new_key_id)
        self.set_current_key(new_key_id)
        logger.info(f"Rotated encryption key from {old_key_id} to {new_key_id}")
        return new_key_id

    def list_keys(self) -> Dict[str, int]:
        """List all keys with versions."""
        return dict(self._key_versions)


class EnvelopeEncryption:
    """
    Envelope encryption: Data encrypted with DEK (Data Encryption Key),
    DEK encrypted with KEK (Key Encryption Key).
    """

    def __init__(self, kek: bytes = None):
        self.kek = kek or os.urandom(32)

    def encrypt(self, plaintext: bytes, associated_data: bytes = None) -> EncryptedData:
        """Encrypt data with envelope encryption."""
        # Generate DEK
        dek = os.urandom(32)

        # Encrypt data with DEK
        aesgcm = AESGCM(dek)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data)

        # Encrypt DEK with KEK
        kek_aesgcm = AESGCM(self.kek)
        kek_nonce = os.urandom(12)
        encrypted_dek = kek_aesgcm.encrypt(kek_nonce, dek, None)

        # Combine
        combined = b"".join([
            len(encrypted_dek).to_bytes(2, 'big'),
            encrypted_dek,
            kek_nonce,
            nonce,
            ciphertext,
        ])

        return EncryptedData(
            ciphertext=combined,
            nonce=kek_nonce,
            key_id="envelope",
            associated_data=associated_data,
        )

    def decrypt(self, encrypted: EncryptedData, associated_data: bytes = None) -> bytes:
        """Decrypt envelope-encrypted data."""
        data = encrypted.ciphertext

        # Parse
        dek_len = int.from_bytes(data[:2], 'big')
        encrypted_dek = data[2:2+dek_len]
        kek_nonce = data[2+dek_len:2+dek_len+12]
        nonce = data[2+dek_len+12:2+dek_len+24]
        ciphertext = data[2+dek_len+24:]

        # Decrypt DEK
        kek_aesgcm = AESGCM(self.kek)
        dek = kek_aesgcm.decrypt(kek_nonce, encrypted_dek, None)

        # Decrypt data
        aesgcm = AESGCM(dek)
        return aesgcm.decrypt(nonce, ciphertext, associated_data or encrypted.associated_data)


class FieldEncryption:
    """Field-level encryption for PII and sensitive data."""

    def __init__(self, key_manager: KeyManager):
        self.key_manager = key_manager

    def encrypt_field(self, value: str, tenant_id: str, field_name: str) -> Dict[str, Any]:
        """Encrypt a field value with tenant-specific key."""
        # Get or create tenant key
        key_id = f"tenant_{tenant_id}"
        key = self.key_manager.get_key(key_id)
        if not key:
            key_id, key = self.key_manager.generate_key(key_id)

        # Encrypt
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        plaintext = value.encode('utf-8')

        # Add field name as associated data for integrity
        associated_data = f"{tenant_id}:{field_name}".encode('utf-8')

        ciphertext = aesgcm.encrypt(nonce, plaintext, associated_data)

        return {
            "encrypted": True,
            "ciphertext": base64.b64encode(ciphertext).decode('ascii'),
            "nonce": base64.b64encode(nonce).decode('ascii'),
            "key_id": key_id,
            "field": field_name,
        }

    def decrypt_field(self, encrypted_data: Dict[str, Any], tenant_id: str, field_name: str) -> str:
        """Decrypt a field value."""
        if not encrypted_data.get("encrypted"):
            return encrypted_data.get("value", "")

        key_id = encrypted_data["key_id"]
        key = self.key_manager.get_key(key_id)
        if not key:
            raise ValueError(f"Key {key_id} not found for decryption")

        aesgcm = AESGCM(key)
        nonce = base64.b64decode(encrypted_data["nonce"])
        ciphertext = base64.b64decode(encrypted_data["ciphertext"])
        associated_data = f"{tenant_id}:{field_name}".encode('utf-8')

        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data)
        return plaintext.decode('utf-8')


class EncryptionManager:
    """Main encryption interface for PraxisFlow."""

    def __init__(self):
        self.key_manager = KeyManager()
        self.field_encryption = FieldEncryption(self.key_manager)
        self.envelope = EnvelopeEncryption()

        # Initialize master key
        master_key = settings.JWT_SECRET.encode('utf-8')[:32].ljust(32, b'0')
        self.key_manager._keys["master"] = master_key
        self.key_manager._current_key_id = "master"

    def encrypt_for_tenant(self, tenant_id: str, data: bytes) -> EncryptedData:
        """Encrypt data with tenant-specific key."""
        key_id = f"tenant_{tenant_id}"
        key = self.key_manager.get_key(key_id)
        if not key:
            key_id, key = self.key_manager.generate_key(key_id)

        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, data, tenant_id.encode('utf-8'))

        return EncryptedData(
            ciphertext=ciphertext,
            nonce=nonce,
            key_id=key_id,
            associated_data=tenant_id.encode('utf-8'),
        )

    def decrypt_for_tenant(self, tenant_id: str, encrypted: EncryptedData) -> bytes:
        """Decrypt data for tenant."""
        key = self.key_manager.get_key(encrypted.key_id)
        if not key:
            raise ValueError(f"Key {encrypted.key_id} not found")

        aesgcm = AESGCM(key)
        return aesgcm.decrypt(
            encrypted.nonce,
            encrypted.ciphertext,
            encrypted.associated_data or tenant_id.encode('utf-8'),
        )

    def encrypt_pii_field(self, tenant_id: str, field_name: str, value: str) -> Dict[str, Any]:
        """Encrypt a PII field."""
        return self.field_encryption.encrypt_field(value, tenant_id, field_name)

    def decrypt_pii_field(self, tenant_id: str, field_name: str, encrypted_data: Dict[str, Any]) -> str:
        """Decrypt a PII field."""
        return self.field_encryption.decrypt_field(encrypted_data, tenant_id, field_name)

    def encrypt_envelope(self, plaintext: bytes, associated_data: bytes = None) -> EncryptedData:
        """Envelope encryption for large payloads."""
        return self.envelope.encrypt(plaintext, associated_data)

    def decrypt_envelope(self, encrypted: EncryptedData, associated_data: bytes = None) -> bytes:
        """Decrypt envelope-encrypted data."""
        return self.envelope.decrypt(encrypted, associated_data)

    def rotate_tenant_key(self, tenant_id: str) -> str:
        """Rotate tenant encryption key."""
        old_key_id = f"tenant_{tenant_id}"
        new_key_id = f"tenant_{tenant_id}_v{self.key_manager._key_versions.get(old_key_id, 0) + 1}"
        self.key_manager.generate_key(new_key_id)
        self.key_manager.set_current_key(new_key_id)
        logger.info(f"Rotated encryption key for tenant {tenant_id}")
        return new_key_id


# Global instance
_encryption_manager: Optional[EncryptionManager] = None


def get_encryption_manager() -> EncryptionManager:
    """Get global encryption manager."""
    global _encryption_manager
    if _encryption_manager is None:
        _encryption_manager = EncryptionManager()
    return _encryption_manager


def encrypt_field(tenant_id: str, field_name: str, value: str) -> Dict[str, Any]:
    """Encrypt a PII field."""
    return get_encryption_manager().encrypt_pii_field(tenant_id, field_name, value)


def decrypt_field(tenant_id: str, field_name: str, encrypted_data: Dict[str, Any]) -> str:
    """Decrypt a PII field."""
    return get_encryption_manager().decrypt_pii_field(tenant_id, field_name, encrypted_data)


def rotate_key(tenant_id: str) -> str:
    """Rotate tenant encryption key."""
    return get_encryption_manager().rotate_tenant_key(tenant_id)


# ─── Exports ───

__all__ = [
    "EncryptedData",
    "KeyManager",
    "EnvelopeEncryption",
    "FieldEncryption",
    "EncryptionManager",
    "get_encryption_manager",
    "encrypt_field",
    "decrypt_field",
    "rotate_key",
]