"""Signed HttpOnly sessions; identity is provisioned server-side, never posted by clients."""

import base64
import hashlib
import hmac
import json
import secrets
import time

from .contracts import Identity
from .settings import ApplicationSettings


def password_hash(password: str, salt: bytes | None = None) -> str:
    if not 8 <= len(password) <= 1024:
        raise ValueError("Password length must be 8-1024")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


class Sessions:
    def __init__(self, settings: ApplicationSettings):
        self.settings = settings
        self.secret = settings.session_secret.get_secret_value().encode()

    def login(self, username: str, password: str) -> str:
        account = self.settings.accounts.get(username)
        # Compute a dummy hash for unknown users to avoid a trivial user-existence oracle.
        stored = account.get("password_hash", "") if account else ""
        try:
            salt, expected = stored.split(":")
            actual = password_hash(password, bytes.fromhex(salt)).split(":")[1]
        except (ValueError, TypeError):
            password_hash("dummy-password", b"0" * 16)
            raise PermissionError("Invalid credentials") from None
        if not hmac.compare_digest(actual, expected):
            raise PermissionError("Invalid credentials")
        identity = Identity(account["organization_id"], account["user_id"], account["role"])
        if identity.role not in {"viewer", "operator", "approver", "admin"}:
            raise PermissionError("Invalid account configuration")
        payload = base64.urlsafe_b64encode(json.dumps({
            **identity.__dict__, "exp": int(time.time()) + self.settings.session_seconds,
            "nonce": secrets.token_hex(16),
        }).encode()).decode()
        return payload + "." + hmac.digest(self.secret, payload.encode(), "sha256").hex()

    def identity(self, token: str) -> Identity:
        try:
            payload, signature = token.split(".")
            if not hmac.compare_digest(signature, hmac.digest(self.secret, payload.encode(), "sha256").hex()):
                raise ValueError()
            data = json.loads(base64.urlsafe_b64decode(payload))
            if data["exp"] <= time.time():
                raise ValueError()
            identity = Identity(data["organization_id"], data["user_id"], data["role"])
            if identity.role not in {"viewer", "operator", "approver", "admin"}:
                raise ValueError()
            # Revocation/role changes take effect even for an unexpired cookie.
            if not any(account.get("organization_id") == identity.organization_id
                       and account.get("user_id") == identity.user_id and account.get("role") == identity.role
                       for account in self.settings.accounts.values()):
                raise ValueError()
            return identity
        except (ValueError, KeyError, TypeError):
            raise PermissionError("Invalid or expired session") from None

    def csrf(self, token: str) -> str:
        return hmac.digest(self.secret, ("csrf:" + token).encode(), "sha256").hex()
