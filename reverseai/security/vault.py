"""Optional encrypted credential vault.

This is intentionally not a required dependency and not enabled by default. It
uses ``cryptography``'s Fernet (AES-128-CBC + HMAC-SHA256) when installed, derives
the key with PBKDF2-HMAC-SHA256, writes files mode 0600, and refuses to open
unless the capability policy explicitly enables ``credential_vault`` *and* a
vault key is present.

If ``cryptography`` is missing, the vault refuses. It never falls back to a
home-grown cipher or to plaintext.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .capabilities import CapabilityDenied, CapabilityPolicy

VAULT_VERSION = 1
KDF_ITERATIONS = 390_000
_KEY_ENV = "REVERSEAI_VAULT_KEY"


class VaultError(Exception):
    pass


class VaultUnavailable(VaultError):
    pass


def _fernet():
    try:
        from cryptography.fernet import Fernet  # type: ignore
    except ImportError as exc:
        raise VaultUnavailable(
            "the encrypted vault requires the optional 'cryptography' package") from exc
    return Fernet


def _derive(key: str, salt: bytes, iterations: int) -> bytes:
    raw = hashlib.pbkdf2_hmac("sha256", key.encode("utf-8"), salt, iterations)
    return base64.urlsafe_b64encode(raw)


class Vault:
    def __init__(self, path: str | os.PathLike, key: str,
                 env: dict[str, str] | None = None,
                 enforce_capability: bool = True) -> None:
        if enforce_capability:
            decision = CapabilityPolicy(env).decision("credential_vault")
            if not decision.allowed:
                raise CapabilityDenied(decision.reason)
        if not key or len(key) < 16:
            raise VaultError(f"{_KEY_ENV} must be at least 16 characters")
        self.path = Path(path)
        self._key = key
        self._fernet_class = _fernet()

    def _load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"version": VAULT_VERSION, "salt": None, "iterations":
                    KDF_ITERATIONS, "secrets": {}}
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VaultError(f"could not read vault: {exc}") from exc
        if not isinstance(data, dict) or data.get("version") != VAULT_VERSION:
            raise VaultError("unsupported vault format")
        return data

    def _save(self, data: dict[str, Any]) -> None:
        import tempfile

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".vault-", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def _cipher(self, data: dict[str, Any]):
        salt = data.get("salt")
        if not salt:
            salt = base64.b64encode(os.urandom(16)).decode("ascii")
            data["salt"] = salt
            data["iterations"] = KDF_ITERATIONS
        raw_salt = base64.b64decode(salt)
        iterations = int(data.get("iterations") or KDF_ITERATIONS)
        return self._fernet_class(_derive(self._key, raw_salt, iterations))

    def put(self, name: str, value: str) -> None:
        name = str(name or "").strip()
        if not name or len(name) > 128:
            raise VaultError("secret name must be 1-128 characters")
        data = self._load()
        token = self._cipher(data).encrypt(str(value).encode("utf-8"))
        data.setdefault("secrets", {})[name] = {
            "token": token.decode("ascii"),
            "updated_at": time.time(),
        }
        self._save(data)

    def get(self, name: str) -> str:
        data = self._load()
        entry = (data.get("secrets") or {}).get(name)
        if not entry:
            raise VaultError(f"no such secret: {name}")
        try:
            return self._cipher(data).decrypt(
                str(entry["token"]).encode("ascii")).decode("utf-8")
        except Exception as exc:
            raise VaultError("could not decrypt the secret") from exc

    def names(self) -> list[str]:
        return sorted((self._load().get("secrets") or {}).keys())

    def delete(self, name: str) -> bool:
        data = self._load()
        secrets = data.get("secrets") or {}
        if name not in secrets:
            return False
        del secrets[name]
        data["secrets"] = secrets
        self._save(data)
        return True
