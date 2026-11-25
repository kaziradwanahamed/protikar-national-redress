"""Citizen SSO (myGov / Porichoy OAuth 2.0 / OIDC) & Mobile OTP verification services."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import CitizenProfile, MobileOTPChallenge, User


@dataclass(frozen=True)
class OIDCUserClaims:
    """Normalized identity claims returned by myGov / Porichoy OIDC or mock provider."""

    subject: str
    full_name_en: str
    full_name_bn: str
    phone_number: str
    email: str = ""
    nid_number: str = ""
    birth_reg_number: str = ""
    address_en: str = ""
    address_bn: str = ""
    bbs_geo_code: str = ""
    utility_accounts: dict[str, str] = field(default_factory=dict)
    saved_documents: list[dict[str, Any]] = field(default_factory=list)
    provider: str = CitizenProfile.IdentityProvider.MYGOV_OIDC


class IdentityVerificationError(ValueError):
    """Raised when OIDC token exchange, Porichoy NID check, or OTP verification fails."""


class BaseIdentityProvider(ABC):
    """Abstract provider interface allowing seamless swap between mock dev & production myGov/Porichoy."""

    @abstractmethod
    def build_authorization_url(self, state: str, nonce: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def exchange_code_for_claims(self, code: str) -> OIDCUserClaims:
        raise NotImplementedError

    @abstractmethod
    def verify_nid_or_birth_reg(
        self, *, nid_number: str = "", birth_reg_number: str = "", date_of_birth: str = ""
    ) -> dict[str, Any]:
        raise NotImplementedError


class MockMyGovPorichoyProvider(BaseIdentityProvider):
    """Deterministic local-development provider for myGov OIDC and Porichoy NID/Birth Reg."""

    def build_authorization_url(self, state: str, nonce: str) -> str:
        params = urlencode(
            {
                "response_type": "code",
                "client_id": settings.MYGOV_OIDC_CLIENT_ID,
                "redirect_uri": settings.MYGOV_OIDC_REDIRECT_URI,
                "scope": "openid profile phone nid address",
                "state": state,
                "nonce": nonce,
                "mock_mode": "true",
            }
        )
        return f"{settings.MYGOV_OIDC_AUTHORIZE_URL}?{params}"

    def exchange_code_for_claims(self, code: str) -> OIDCUserClaims:
        if not code or code.startswith("invalid"):
            raise IdentityVerificationError("Invalid or expired myGov authorization code.")

        suffix = hashlib.sha256(code.encode("utf-8")).hexdigest()[:8]
        nid_digits = str(int(suffix, 16))[:10].ljust(10, "7")
        return OIDCUserClaims(
            subject=f"mygov-sub-{suffix}",
            full_name_en=f"Tanvir Ahmed ({suffix[:4]})",
            full_name_bn="তানভীর আহমেদ",
            phone_number=f"+88017{nid_digits[:8]}",
            email=f"citizen.{suffix[:6]}@mygov.local",
            nid_number=nid_digits,
            address_en="House 14, Road 45, Gulshan-2, Dhaka-1212",
            address_bn="বাসা ১৪, রোড ৪৫, গুলশান-২, ঢাকা-১২১২",
            bbs_geo_code="30262619",
            utility_accounts={
                "desco_account": f"DESCO-{suffix[:6].upper()}",
                "dwasa_account": f"DWASA-{suffix[:6].upper()}",
            },
            saved_documents=[
                {
                    "doc_type": "NID_SMART_CARD",
                    "object_key": f"citizen-docs/{suffix}/nid_front.enc",
                    "verified": True,
                }
            ],
            provider=CitizenProfile.IdentityProvider.MYGOV_OIDC,
        )

    def verify_nid_or_birth_reg(
        self, *, nid_number: str = "", birth_reg_number: str = "", date_of_birth: str = ""
    ) -> dict[str, Any]:
        if nid_number and len(nid_number) in (10, 13, 17) and nid_number.isdigit():
            return {
                "verified": True,
                "id_type": "NID",
                "id_last4": nid_number[-4:],
                "full_name_en": "Verified Citizen (Porichoy Mock)",
                "full_name_bn": "যাচাইকৃত নাগরিক",
                "address_en": "Mirpur-10, Dhaka-1216",
                "address_bn": "মিরপুর-১০, ঢাকা-১২১৬",
                "bbs_geo_code": "302648",
            }
        if birth_reg_number and len(birth_reg_number) == 17 and birth_reg_number.isdigit():
            return {
                "verified": True,
                "id_type": "BIRTH_REG",
                "id_last4": birth_reg_number[-4:],
                "full_name_en": "Verified Citizen (BDRIS Mock)",
                "full_name_bn": "যাচাইকৃত নাগরিক (জন্ম নিবন্ধন)",
                "address_en": "Savar, Dhaka-1340",
                "address_bn": "সাভার, ঢাকা-১৩৪০",
                "bbs_geo_code": "302672",
            }
        raise IdentityVerificationError(
            "Provide a valid 10/13/17-digit NID or 17-digit Birth Registration Number."
        )


class MyGovPorichoyOIDCProvider(BaseIdentityProvider):
    """Production OAuth 2.0 / OIDC & Porichoy verification client over HTTPS."""

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout_seconds = timeout_seconds

    def build_authorization_url(self, state: str, nonce: str) -> str:
        params = urlencode(
            {
                "response_type": "code",
                "client_id": settings.MYGOV_OIDC_CLIENT_ID,
                "redirect_uri": settings.MYGOV_OIDC_REDIRECT_URI,
                "scope": "openid profile phone nid address",
                "state": state,
                "nonce": nonce,
            }
        )
        return f"{settings.MYGOV_OIDC_AUTHORIZE_URL}?{params}"

    def exchange_code_for_claims(self, code: str) -> OIDCUserClaims:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            token_resp = client.post(
                settings.MYGOV_OIDC_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.MYGOV_OIDC_REDIRECT_URI,
                    "client_id": settings.MYGOV_OIDC_CLIENT_ID,
                    "client_secret": settings.MYGOV_OIDC_CLIENT_SECRET,
                },
            )
            if token_resp.status_code != 200:
                raise IdentityVerificationError(
                    f"myGov token exchange failed with status {token_resp.status_code}."
                )
            access_token = token_resp.json().get("access_token")
            if not access_token:
                raise IdentityVerificationError("myGov token response omitted access_token.")

            userinfo_resp = client.get(
                settings.MYGOV_OIDC_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_resp.status_code != 200:
                raise IdentityVerificationError(
                    f"myGov userinfo fetch failed with status {userinfo_resp.status_code}."
                )
            data = userinfo_resp.json()

        return OIDCUserClaims(
            subject=str(data["sub"]),
            full_name_en=data.get("name", ""),
            full_name_bn=data.get("name_bn", ""),
            phone_number=data.get("phone_number", ""),
            email=data.get("email", ""),
            nid_number=data.get("nid", ""),
            birth_reg_number=data.get("birth_registration_no", ""),
            address_en=data.get("address_en", ""),
            address_bn=data.get("address_bn", ""),
            bbs_geo_code=data.get("bbs_geo_code", ""),
            utility_accounts=data.get("utility_accounts", {}),
            saved_documents=data.get("saved_documents", []),
            provider=CitizenProfile.IdentityProvider.MYGOV_OIDC,
        )

    def verify_nid_or_birth_reg(
        self, *, nid_number: str = "", birth_reg_number: str = "", date_of_birth: str = ""
    ) -> dict[str, Any]:
        payload = {"person_dob": date_of_birth}
        if nid_number:
            payload["national_id"] = nid_number
        elif birth_reg_number:
            payload["birth_registration_number"] = birth_reg_number
        else:
            raise IdentityVerificationError("Either nid_number or birth_reg_number is required.")

        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.post(
                settings.PORICHOY_API_URL,
                json=payload,
                headers={"x-api-key": settings.PORICHOY_API_KEY},
            )
            if resp.status_code != 200:
                raise IdentityVerificationError(
                    f"Porichoy verification failed with status {resp.status_code}."
                )
            body = resp.json()
            if not body.get("passKyc") == "yes":
                raise IdentityVerificationError("Porichoy KYC verification did not pass.")
            citizen = body.get("voter", {})
            raw_id = nid_number or birth_reg_number
            return {
                "verified": True,
                "id_type": "NID" if nid_number else "BIRTH_REG",
                "id_last4": raw_id[-4:],
                "full_name_en": citizen.get("nameEn", ""),
                "full_name_bn": citizen.get("name", ""),
                "address_en": citizen.get("presentAddress", ""),
                "address_bn": citizen.get("presentAddressBn", ""),
                "bbs_geo_code": citizen.get("bbsGeoCode", ""),
            }


def get_identity_provider() -> BaseIdentityProvider:
    if getattr(settings, "IDENTITY_PROVIDER_MODE", "mock").lower() == "production":
        return MyGovPorichoyOIDCProvider()
    return MockMyGovPorichoyProvider()


class MobileOTPService:
    """Issues and verifies rate-limited 6-digit Mobile OTPs stored strictly as SHA-256 hashes."""

    OTP_TTL_MINUTES = 5

    @staticmethod
    def _hash_otp(phone_number: str, otp_code: str) -> str:
        secret = getattr(settings, "UCT_HMAC_SECRET", settings.SECRET_KEY).encode("utf-8")
        return hmac.new(secret, f"{phone_number}:{otp_code}".encode("utf-8"), hashlib.sha256).hexdigest()

    @classmethod
    def issue_challenge(
        cls, phone_number: str, purpose: str = MobileOTPChallenge.Purpose.LOGIN
    ) -> tuple[MobileOTPChallenge, str]:
        otp_code = f"{secrets.randbelow(900_000) + 100_000:06d}"
        challenge = MobileOTPChallenge.objects.create(
            phone_number=phone_number,
            otp_hash=cls._hash_otp(phone_number, otp_code),
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=cls.OTP_TTL_MINUTES),
        )
        return challenge, otp_code

    @classmethod
    def verify_challenge(cls, challenge_id, phone_number: str, otp_code: str) -> MobileOTPChallenge:
        try:
            challenge = MobileOTPChallenge.objects.get(
                challenge_id=challenge_id, phone_number=phone_number
            )
        except MobileOTPChallenge.DoesNotExist as exc:
            raise IdentityVerificationError("OTP challenge not found.") from exc

        if challenge.is_consumed:
            raise IdentityVerificationError("OTP challenge has already been used.")
        if challenge.is_expired:
            raise IdentityVerificationError("OTP challenge has expired.")
        if challenge.attempts >= challenge.max_attempts:
            raise IdentityVerificationError("Maximum OTP verification attempts exceeded.")

        expected = cls._hash_otp(phone_number, otp_code)
        if not hmac.compare_digest(challenge.otp_hash, expected):
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
            raise IdentityVerificationError("Invalid OTP code.")

        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=["consumed_at"])
        return challenge


class CitizenIdentityService:
    """Generates persistent UCT & Pseudonymous Public Hash and auto-fills CitizenProfile."""

    @staticmethod
    def compute_nid_hash(canonical_id: str) -> str:
        secret = getattr(settings, "UCT_HMAC_SECRET", settings.SECRET_KEY).encode("utf-8")
        return hmac.new(secret, f"nid:{canonical_id}".encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def compute_uct(canonical_id: str) -> str:
        secret = getattr(settings, "UCT_HMAC_SECRET", settings.SECRET_KEY).encode("utf-8")
        digest = hmac.new(secret, f"uct:{canonical_id}".encode("utf-8"), hashlib.sha256).hexdigest()
        return f"UCT-{digest[:40].upper()}"

    @staticmethod
    def compute_pseudonymous_hash(uct: str) -> str:
        secret = getattr(settings, "UCT_HMAC_SECRET", settings.SECRET_KEY).encode("utf-8")
        return hmac.new(secret, f"pub:{uct}".encode("utf-8"), hashlib.sha256).hexdigest()

    @classmethod
    @transaction.atomic
    def upsert_from_oidc_claims(cls, claims: OIDCUserClaims) -> tuple[User, CitizenProfile]:
        canonical_id = claims.nid_number or claims.birth_reg_number or claims.subject
        nid_hash = cls.compute_nid_hash(canonical_id)
        uct = cls.compute_uct(canonical_id)
        public_hash = cls.compute_pseudonymous_hash(uct)

        first_name, _, last_name = claims.full_name_en.partition(" ")
        user, created = User.objects.get_or_create(
            nid_hash=nid_hash,
            defaults={
                "username": f"cit_{public_hash[:16]}",
                "first_name": first_name[:150],
                "last_name": last_name[:150],
                "email": claims.email,
                "phone_number": claims.phone_number,
                "account_type": User.AccountType.CITIZEN,
            },
        )
        if not created:
            user.phone_number = claims.phone_number or user.phone_number
            user.email = claims.email or user.email
            user.save(update_fields=["phone_number", "email"])

        profile, _ = CitizenProfile.objects.update_or_create(
            user=user,
            defaults={
                "unified_citizen_token": uct,
                "pseudonymous_public_hash": public_hash,
                "identity_provider": claims.provider,
                "identity_verified": True,
                "verified_at": timezone.now(),
                "nid_last4": claims.nid_number[-4:] if claims.nid_number else "",
                "birth_reg_last4": claims.birth_reg_number[-4:] if claims.birth_reg_number else "",
                "saved_address_en": claims.address_en,
                "saved_address_bn": claims.address_bn,
                "saved_bbs_geo_code": claims.bbs_geo_code,
                "utility_accounts": claims.utility_accounts,
                "saved_documents": claims.saved_documents,
            },
        )
        return user, profile

    @classmethod
    @transaction.atomic
    def verify_otp_and_identity(
        cls,
        *,
        challenge_id,
        phone_number: str,
        otp_code: str,
        nid_number: str = "",
        birth_reg_number: str = "",
        date_of_birth: str = "",
    ) -> tuple[User, CitizenProfile]:
        MobileOTPService.verify_challenge(challenge_id, phone_number, otp_code)
        provider = get_identity_provider()
        kyc = provider.verify_nid_or_birth_reg(
            nid_number=nid_number,
            birth_reg_number=birth_reg_number,
            date_of_birth=date_of_birth,
        )
        claims = OIDCUserClaims(
            subject=f"otp-{phone_number}",
            full_name_en=kyc["full_name_en"],
            full_name_bn=kyc["full_name_bn"],
            phone_number=phone_number,
            nid_number=nid_number,
            birth_reg_number=birth_reg_number,
            address_en=kyc.get("address_en", ""),
            address_bn=kyc.get("address_bn", ""),
            bbs_geo_code=kyc.get("bbs_geo_code", ""),
            provider=(
                CitizenProfile.IdentityProvider.PORICHOY_NID
                if nid_number
                else CitizenProfile.IdentityProvider.BIRTH_REG
            ),
        )
        return cls.upsert_from_oidc_claims(claims)
