import base64
from binascii import Error as Base64Error
from hashlib import sha256
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretBoxError(RuntimeError):
    pass


class SecretBox:
    """Versioned authenticated encryption for short-lived durable job secrets."""

    VERSION = "v1"

    def __init__(self, root_secret: str) -> None:
        self.key = sha256(f"flowforge-job-secrets:{root_secret}".encode("utf-8")).digest()

    def encrypt(self, plaintext: str, purpose: str) -> str:
        nonce = os.urandom(12)
        associated_data = f"flowforge:{purpose}:{self.VERSION}".encode("utf-8")
        ciphertext = AESGCM(self.key).encrypt(
            nonce,
            plaintext.encode("utf-8"),
            associated_data,
        )
        encoded = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii").rstrip("=")
        return f"{self.VERSION}.{encoded}"

    def decrypt(self, envelope: str, purpose: str) -> str:
        try:
            version, encoded = envelope.split(".", 1)
            if version != self.VERSION:
                raise SecretBoxError("Unsupported encrypted secret version")
            padding = "=" * (-len(encoded) % 4)
            combined = base64.urlsafe_b64decode(encoded + padding)
            nonce, ciphertext = combined[:12], combined[12:]
            if len(nonce) != 12 or not ciphertext:
                raise ValueError("invalid envelope")
            associated_data = f"flowforge:{purpose}:{version}".encode("utf-8")
            plaintext = AESGCM(self.key).decrypt(nonce, ciphertext, associated_data)
            return plaintext.decode("utf-8")
        except (Base64Error, InvalidTag, UnicodeDecodeError, ValueError) as error:
            raise SecretBoxError("Encrypted job secret could not be opened") from error
