import os
from functools import lru_cache

from cryptography.fernet import Fernet


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.environ.get("PLAID_TOKEN_ENCRYPTION_KEY", "")
    if not key:
        # Lazy + loud: app and migrations can import without the key set,
        # but any actual token round-trip fails fast with a useful message.
        raise RuntimeError(
            "PLAID_TOKEN_ENCRYPTION_KEY is not set. Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
