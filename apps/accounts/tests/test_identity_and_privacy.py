import uuid
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import CitizenProfile, User
from apps.accounts.services.oidc_providers import (
    CitizenIdentityService,
    IdentityVerificationError,
    MobileOTPService,
    get_identity_provider,
)
from apps.accounts.services.vault_envelope import (
    VaultAuthorizationError,
    WhistleblowerPrivacyService,
)
from apps.complaints.models import AuditLog, Complaint


@override_settings(IDENTITY_PROVIDER_MODE="mock", VAULT_MODE="local_dev")
class CitizenSSOAndStrikeTests(TestCase):
    def test_mygov_oidc_generates_persistent_uct_and_autofill_profile(self):
        provider = get_identity_provider()
        claims = provider.exchange_code_for_claims("demo-code-2026")
        user_1, profile_1 = CitizenIdentityService.upsert_from_oidc_claims(claims)
        user_2, profile_2 = CitizenIdentityService.upsert_from_oidc_claims(claims)

        self.assertEqual(user_1.id, user_2.id)
        self.assertEqual(profile_1.unified_citizen_token, profile_2.unified_citizen_token)
        self.assertTrue(profile_1.unified_citizen_token.startswith("UCT-"))
        self.assertEqual(len(profile_1.pseudonymous_public_hash), 64)
        self.assertTrue(profile_1.identity_verified)
        self.assertIn("desco_account", profile_1.utility_accounts)
        self.assertEqual(profile_1.saved_bbs_geo_code, "30262619")

    def test_mobile_otp_and_porichoy_nid_verification_flow(self):
        challenge, otp = MobileOTPService.issue_challenge("+8801711000099")
        user, profile = CitizenIdentityService.verify_otp_and_identity(
            challenge_id=challenge.challenge_id,
            phone_number="+8801711000099",
            otp_code=otp,
            nid_number="1990123456",
            date_of_birth="1990-05-14",
        )
        self.assertEqual(user.phone_number, "+8801711000099")
        self.assertEqual(profile.nid_last4, "3456")
        self.assertEqual(profile.identity_provider, CitizenProfile.IdentityProvider.PORICHOY_NID)

        with self.assertRaises(IdentityVerificationError):
            MobileOTPService.verify_challenge(challenge.challenge_id, "+8801711000099", otp)

    def test_three_verified_false_filings_trigger_premoderation_and_revoke_priority(self):
        claims = get_identity_provider().exchange_code_for_claims("strike-test-code")
        _user, profile = CitizenIdentityService.upsert_from_oidc_claims(claims)

        self.assertEqual(profile.credibility_score, 100.0)
        self.assertFalse(profile.requires_manual_premoderation)
        self.assertTrue(profile.priority_routing_eligible)

        profile.record_verified_false_filing("False report #1 verified by field inspection.")
        profile.record_verified_false_filing("False report #2 verified by field inspection.")
        self.assertEqual(profile.strike_count, 2)
        self.assertFalse(profile.requires_manual_premoderation)
        self.assertTrue(profile.priority_routing_eligible)

        profile.record_verified_false_filing("False report #3 verified by GRO & supervisor.")
        self.assertEqual(profile.strike_count, 3)
        self.assertEqual(profile.credibility_score, 25.0)
        self.assertTrue(profile.requires_manual_premoderation)
        self.assertFalse(profile.priority_routing_eligible)


@override_settings(IDENTITY_PROVIDER_MODE="mock", VAULT_MODE="local_dev")
class WhistleblowerVaultEnvelopeTests(TestCase):
    def setUp(self):
        claims = get_identity_provider().exchange_code_for_claims("whistleblower-citizen-1")
        self.citizen, self.profile = CitizenIdentityService.upsert_from_oidc_claims(claims)
        self.gro_officer = User.objects.create_user(
            username="gro_dncc_19",
            password="StrongPassword123!",
            account_type=User.AccountType.OFFICER,
            doptor_officer_id="OFF-DNCC-1019",
            doptor_seat_id="SEAT-DNCC-GRO-19",
            doptor_role_level="GRO",
            is_oversight_cell=False,
        )
        self.oversight_officer = User.objects.create_user(
            username="oversight_director",
            password="StrongPassword123!",
            account_type=User.AccountType.ARBITRATOR,
            doptor_officer_id="OFF-CAB-0001",
            doptor_seat_id="SEAT-OVERSIGHT-01",
            doptor_role_level="APPELLATE",
            is_oversight_cell=True,
        )
        self.complaint = Complaint.objects.create(
            citizen_uct_hash=self.profile.pseudonymous_public_hash,
            is_anonymous=True,
            raw_text_en="Alleged bribery at local ward office.",
            admin_geo_code="30262619",
        )

    def test_masking_and_envelope_encryption_unseal_rbac(self):
        service = WhistleblowerPrivacyService()
        record = service.seal_identity(
            complaint_id=self.complaint.complaint_id,
            citizen_profile=self.profile,
        )
        self.assertTrue(record.wrapped_dek.startswith("vault:v1:"))
        self.assertNotIn(self.citizen.phone_number, record.encrypted_payload)

        masked = service.mask_citizen_for_viewer(
            is_anonymous=True,
            citizen_name=self.citizen.get_full_name(),
            citizen_phone=self.citizen.phone_number,
            pseudonymous_hash=self.profile.pseudonymous_public_hash,
            viewer_user=self.gro_officer,
        )
        self.assertEqual(masked["phone_number"], "***-MASKED-***")
        self.assertFalse(masked["oversight_unseal_permitted"])

        with self.assertRaises(VaultAuthorizationError):
            service.unseal_identity(
                complaint_id=self.complaint.complaint_id,
                oversight_user=self.gro_officer,
                justification="Attempting unauthorized unseal from GRO seat.",
            )

        unsealed = service.unseal_identity(
            complaint_id=self.complaint.complaint_id,
            oversight_user=self.oversight_officer,
            justification="Cabinet Oversight Cell anti-corruption tribunal subpoena #2026-44.",
        )
        self.assertEqual(unsealed["phone_number"], self.citizen.phone_number)
        self.assertEqual(unsealed["unified_citizen_token"], self.profile.unified_citizen_token)

        self.assertTrue(
            AuditLog.objects.filter(
                complaint=self.complaint,
                action="WHISTLEBLOWER_IDENTITY_UNSEALED",
            ).exists()
        )
        is_valid, _checked, broken = AuditLog.verify_chain()
        self.assertTrue(is_valid)
        self.assertIsNone(broken)

    def test_whistleblower_unseal_endpoint_enforces_oversight_rbac(self):
        WhistleblowerPrivacyService().seal_identity(
            complaint_id=self.complaint.complaint_id,
            citizen_profile=self.profile,
        )
        client = APIClient()
        url = f"/api/v1/accounts/whistleblower/{self.complaint.complaint_id}/unseal/"
        payload = {"justification": "Cabinet Oversight Cell formal inquiry order #882."}

        client.force_authenticate(user=self.gro_officer)
        resp_forbidden = client.post(url, payload, format="json")
        self.assertEqual(resp_forbidden.status_code, 403)

        client.force_authenticate(user=self.oversight_officer)
        resp_ok = client.post(url, payload, format="json")
        self.assertEqual(resp_ok.status_code, 200)
        self.assertEqual(resp_ok.data["unsealed_identity"]["phone_number"], self.citizen.phone_number)
