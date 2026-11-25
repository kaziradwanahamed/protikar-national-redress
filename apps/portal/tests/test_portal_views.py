import json
from django.test import TestCase
from django.urls import reverse


class PortalViewsAndI18nTests(TestCase):
    def test_all_portal_pages_render_200(self):
        for name in (
            "portal:home",
            "portal:udc-desk",
            "portal:officer-workspace",
            "portal:field-worker",
            "portal:command-center",
            "portal:export-ddcc-pdf",
        ):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 200, f"Expected 200 for {name}")

    def test_ddcc_csv_export_headers(self):
        resp = self.client.get(reverse("portal:export-ddcc-csv"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        self.assertIn("Tracking Code", resp.content.decode("utf-8"))

    def test_bangla_english_language_switch(self):
        resp = self.client.post(
            reverse("portal:set-language"),
            {"lang": "bn", "next": reverse("portal:home")},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'lang="bn"')
        self.assertContains(resp, "প্রতিকার জাতীয় অভিযোগ নিষ্পত্তি")

    def test_pwa_manifest_and_service_worker_endpoints(self):
        manifest_resp = self.client.get(reverse("portal:pwa-manifest"))
        self.assertEqual(manifest_resp.status_code, 200)
        data = json.loads(manifest_resp.content.decode("utf-8"))
        self.assertEqual(data["start_url"], "/officer/field/")

        sw_resp = self.client.get(reverse("portal:pwa-sw"))
        self.assertEqual(sw_resp.status_code, 200)
        self.assertEqual(sw_resp["Service-Worker-Allowed"], "/")
        self.assertIn("sync-field-resolutions", sw_resp.content.decode("utf-8"))
