"""
Envelope Encryption Service for Anonymous / Whistleblower Identity Protection.

Uses per-record 256-bit AES-GCM Data Encryption Keys (DEKs) wrapped by HashiCorp Vault's
Transit Secrets Engine (or an HKDF-derived local KEK in dev/test mode).
"""

from __future__ import annotations

import base64
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import CitizenProfile, User, WhistleblowerVaultRecord
from apps.complaints.models import AuditLog


class VaultAuthorizationError(PermissionError):
    """Raised when a non-Oversight-Cell actor attempts to unseal whistleblower identity."""


class VaultEnvelopeError(RuntimeError):
    """Raised on Vault Transit encryption/decryption or ciphertext integrity failure."""


@dataclass(frozen=True)
class EnvelopeCiphertext:
    vault_key_name: str
    wrapped_dek: str
    encrypted_payload: str
    nonce_b64: str


class BaseVaultTransitClient(ABC):
    @abstractmethod
    def wrap_dek(self, key_name: str, plaintext_dek: bytes) -> str:
        raise NotImplementedError

    @abstractmethod
    def unwrap_dek(self, key_name: str, wrapped_dek: str) -> bytes:
        raise NotImplementedError


class LocalDevVaultTransitClient(BaseVaultTransitClient):
    """Deterministic local-dev KEK wrapper mimicking HashiCorp Vault Transit `vault:v1:` format."""

    def __init__(self, master_secret: str):
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"bd-grievance-vault-transit-v1",
            info=b"whistleblower-kek",
        )
        self._kek = hkdf.derive(master_secret.encode("utf-8"))

    def wrap_dek(self, key_name: str, plaintext_dek: bytes) -> str:
        nonce = os.urandom(12)
        aes = AESGCM(self._kek)
        ct = aes.encrypt(nonce, plaintext_dek, associated_data=key_name.encode("utf-8"))
        blob = base64.b64encode(nonce + ct).decode("ascii")
        return f"vault:v1:{blob}"

    def unwrap_dek(self, key_name: str, wrapped_dek: str) -> bytes:
        if not wrapped_dek.startswith("vault:v1:"):
            raise VaultEnvelopeError("Malformed wrapped DEK format.")
        raw = base64.b64decode(wrapped_dek.removeprefix("vault:v1:"))
        nonce, ct = raw[:12], raw[12:]
        aes = AESGCM(self._kek)
        try:
            return aes.decrypt(nonce, ct, associated_data=key_name.encode("utf-8"))
        except Exception as exc:
            raise VaultEnvelopeError("Failed to unwrap DEK with local KEK.") from exc


class HashiCorpVaultTransitClient(BaseVaultTransitClient):
    """Production HashiCorp Vault Transit Engine client over HTTP(S)."""

    def __init__(self, vault_addr: str, vault_token: str, timeout_seconds: float = 8.0):
        self.vault_addr = vault_addr.rstrip("/")
        self.vault_token = vault_token
        self.timeout_seconds = timeout_seconds

    def wrap_dek(self, key_name: str, plaintext_dek: bytes) -> str:
        url = f"{self.vault_addr}/v1/transit/encrypt/{key_name}"
        payload = {"plaintext": base64.b64encode(plaintext_dek).decode("ascii")}
        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.post(url, json=payload, headers={"X-Vault-Token": self.vault_token})
            if resp.status_code != 200:
                raise VaultEnvelopeError(f"Vault Transit encrypt failed: HTTP {resp.status_code}")
            return resp.json()["data"]["ciphertext"]

    def unwrap_dek(self, key_name: str, wrapped_dek: str) -> bytes:
        url = f"{self.vault_addr}/v1/transit/decrypt/{key_name}"
        payload = {"ciphertext": wrapped_dek}
        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.post(url, json=payload, headers={"X-Vault-Token": self.vault_token})
            if resp.status_code != 200:
                raise VaultEnvelopeError(f"Vault Transit decrypt failed: HTTP {resp.status_code}")
            b64_plain = resp.json()["data"]["plaintext"]
            return base64.b64decode(b64_plain)


def get_vault_transit_client() -> BaseVaultTransitClient:
    mode = getattr(settings, "VAULT_MODE", "local_dev").lower()
    if mode == "hashicorp":
        return HashiCorpVaultTransitClient(
            vault_addr=settings.VAULT_ADDR,
            vault_token=settings.VAULT_TOKEN,
        )
    return LocalDevVaultTransitClient(master_secret=settings.VAULT_LOCAL_MASTER_KEY)


class WhistleblowerPrivacyService:
    """
    Decouples Identity Verification from Identity Visibility for whistleblower complaints.
    - Masks citizen name/phone from local GRO / Field Worker views when is_anonymous=True.
    - Seals real identity using AES-256-GCM envelope encryption wrapped by Vault Transit.
    - Permits unsealing ONLY for Oversight Cell roles and writes an immutable AuditLog entry.
    """

    def __init__(self, vault_client: BaseVaultTransitClient | None = None, key_name: str | None = None):
        self.vault_client = vault_client or get_vault_transit_client()
        self.key_name = key_name or getattr(settings, "VAULT_TRANSIT_KEY", "whistleblower-transit-key")

    def encrypt_envelope(self, identity_payload: dict[str, Any], aad: str) -> EnvelopeCiphertext:
        dek = os.urandom(32)
        nonce = os.urandom(12)
        plaintext = json.dumps(identity_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ct = AESGCM(dek).encrypt(nonce, plaintext, associated_data=aad.encode("utf-8"))
        wrapped_dek = self.vault_client.wrap_dek(self.key_name, dek)
        return EnvelopeCiphertext(
            vault_key_name=self.key_name,
            wrapped_dek=wrapped_dek,
            encrypted_payload=base64.b64encode(ct).decode("ascii"),
            nonce_b64=base64.b64encode(nonce).decode("ascii"),
        )

    def decrypt_envelope(self, record: WhistleblowerVaultRecord, aad: str) -> dict[str, Any]:
        dek = self.vault_client.unwrap_dek(record.vault_key_name, record.wrapped_dek)
        nonce = base64.b64decode(record.nonce_b64)
        ct = base64.b64decode(record.encrypted_payload)
        try:
            plaintext = AESGCM(dek).decrypt(nonce, ct, associated_data=aad.encode("utf-8"))
        except Exception as exc:
            raise VaultEnvelopeError("Whistleblower ciphertext authentication failed.") from exc
        return json.loads(plaintext.decode("utf-8"))

    @transaction.atomic
    def seal_identity(self, *, complaint_id, citizen_profile: CitizenProfile) -> WhistleblowerVaultRecord:
        user = citizen_profile.user
        payload = {
            "user_id": str(user.id),
            "full_name": user.get_full_name() or user.username,
            "phone_number": user.phone_number,
            "email": user.email,
            "nid_hash": user.nid_hash,
            "unified_citizen_token": citizen_profile.unified_citizen_token,
            "saved_bbs_geo_code": citizen_profile.saved_bbs_geo_code,
        }
        envelope = self.encrypt_envelope(payload, aad=str(complaint_id))
        record, _ = WhistleblowerVaultRecord.objects.update_or_create(
            complaint_id=complaint_id,
            defaults={
                "pseudonymous_public_hash": citizen_profile.pseudonymous_public_hash,
                "vault_key_name": envelope.vault_key_name,
                "wrapped_dek": envelope.wrapped_dek,
                "encrypted_payload": envelope.encrypted_payload,
                "nonce_b64": envelope.nonce_b64,
            },
        )
        return record

    @transaction.atomic
    def unseal_identity(
        self, *, complaint_id, oversight_user: User, justification: str
    ) -> dict[str, Any]:
        if not (oversight_user and oversight_user.is_authenticated and oversight_user.is_oversight_cell):
            raise VaultAuthorizationError(
                "Only authorized Oversight Cell personnel may unseal whistleblower identities."
            )
        if not justification or len(justification.strip()) < 10:
            raise ValueError("A written justification (>=10 chars) is required to unseal identity.")

        record = WhistleblowerVaultRecord.objects.select_for_update().get(complaint_id=complaint_id)
        identity = self.decrypt_envelope(record, aad=str(complaint_id))

        record.unsealed_count += 1
        record.last_unsealed_by = oversight_user
        record.last_unsealed_at = timezone.now()
        record.save(update_fields=["unsealed_count", "last_unsealed_by", "last_unsealed_at"])

        AuditLog.objects.create(
            complaint_id=complaint_id,
            actor_id=str(oversight_user.id),
            actor_seat_id=oversight_user.doptor_seat_id or "OVERSIGHT-CELL",
            actor_role="OVERSIGHT_CELL",
            action="WHISTLEBLOWER_IDENTITY_UNSEALED",
            entity_type="WhistleblowerVaultRecord",
            entity_id=str(record.record_id),
            payload={
                "justification": justification.strip(),
                "unsealed_count": record.unsealed_count,
            },
        )
        return identity

    @staticmethod
    def mask_citizen_for_viewer(
        *,
        is_anonymous: bool,
        citizen_name: str,
        citizen_phone: str,
        pseudonymous_hash: str,
        viewer_user: User | None,
    ) -> dict[str, Any]:
        """Mask citizen PII from local field workers and GROs when is_anonymous=True."""
        if not is_anonymous:
            return {
                "is_anonymous": False,
                "display_name": citizen_name,
                "phone_number": citizen_phone,
                "pseudonymous_public_hash": pseudonymous_hash,
            }

        can_unseal = bool(
            viewer_user and viewer_user.is_authenticated and viewer_user.is_oversight_cell
        )
        return {
            "is_anonymous": True,
            "display_name": f"Protected Whistleblower ({pseudonymous_hash[:8]})",
            "phone_number": "***-MASKED-***",
            "pseudonymous_public_hash": pseudonymous_hash,
            "oversight_unseal_permitted": can_unseal,
        }
