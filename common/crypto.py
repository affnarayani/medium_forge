"""
common/crypto.py
Shared cookie decryption utilities.
Decrypts AESGCM-encrypted cookie payloads using DECRYPT_KEY from environment.
"""

import base64
import json
import os
from typing import List, Dict, Any

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from dotenv import load_dotenv

from common.config_loader import get

PBKDF2_ITERATIONS = 200_000


def get_env_decrypt_key():
    """Load .env and ensure DECRYPT_KEY is available. Returns the key string."""
    load_dotenv()
    key = os.getenv("DECRYPT_KEY")
    if not key:
        raise RuntimeError("DECRYPT_KEY missing from environment/.env")
    return key


def _derive_key(password: bytes, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(password)


def _decrypt_payload(payload: Dict[str, Any], password: str) -> bytes:
    salt = base64.b64decode(payload["s"])
    nonce = base64.b64decode(payload["n"])
    ciphertext = base64.b64decode(payload["ct"])

    key = _derive_key(password.encode("utf-8"), salt)
    aesgcm = AESGCM(key)

    try:
        return aesgcm.decrypt(nonce, ciphertext, None)
    except InvalidTag:
        raise RuntimeError("Decryption failed (InvalidTag)")


def _normalize_cookies(cookies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize SameSite and PartitionKey values for Playwright compatibility."""
    for c in cookies:
        if "partitionKey" in c and isinstance(c["partitionKey"], dict):
            if "topLevelSite" in c["partitionKey"]:
                c["partitionKey"] = str(c["partitionKey"]["topLevelSite"])
            else:
                del c["partitionKey"]

        if "sameSite" in c:
            val = str(c["sameSite"]).lower()
            if val in ["no_restriction", "none", "unspecified", "null"]:
                c["sameSite"] = "None"
            elif val == "lax":
                c["sameSite"] = "Lax"
            elif val == "strict":
                c["sameSite"] = "Strict"
            else:
                c["sameSite"] = "Lax"
    return cookies


def load_cookies(file_path) -> List[Dict[str, Any]]:
    """Load and decrypt cookies from an encrypted JSON file."""
    print("[STEP] Loading cookies...", flush=True)

    password = get_env_decrypt_key()

    with open(file_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    plaintext = _decrypt_payload(payload, password)
    cookies = json.loads(plaintext.decode("utf-8"))
    cookies = _normalize_cookies(cookies)

    print("[OK] Cookies loaded", flush=True)
    return cookies