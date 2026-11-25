"""
Bangla Geo-NER, Infrastructure Ownership Hinting & P1 Life-Safety Rescue Filter.
Extracts Division/District/Upazila/Union/Ward entities, distinguishes City Corp vs.
RHD national highway vs. LGED rural roads, and flags acute rescue keywords as P1.
"""

from __future__ import annotations

from typing import Any


GAZETTEER: dict[str, dict[str, str]] = {
    "গুলশান": {"division": "Dhaka", "district": "Dhaka", "upazila": "Gulshan", "union_or_ward": "DNCC Ward 19", "bbs_geo_code": "30262619"},
    "gulshan": {"division": "Dhaka", "district": "Dhaka", "upazila": "Gulshan", "union_or_ward": "DNCC Ward 19", "bbs_geo_code": "30262619"},
    "মিরপুর": {"division": "Dhaka", "district": "Dhaka", "upazila": "Mirpur", "union_or_ward": "DNCC Zone 2", "bbs_geo_code": "302648"},
    "mirpur": {"division": "Dhaka", "district": "Dhaka", "upazila": "Mirpur", "union_or_ward": "DNCC Zone 2", "bbs_geo_code": "302648"},
    "মতিঝিল": {"division": "Dhaka", "district": "Dhaka", "upazila": "Motijheel", "union_or_ward": "DSCC Ward 20", "bbs_geo_code": "30265420"},
    "motijheel": {"division": "Dhaka", "district": "Dhaka", "upazila": "Motijheel", "union_or_ward": "DSCC Ward 20", "bbs_geo_code": "30265420"},
    "সাভার": {"division": "Dhaka", "district": "Dhaka", "upazila": "Savar", "union_or_ward": "Savar Pourashava", "bbs_geo_code": "302672"},
    "savar": {"division": "Dhaka", "district": "Dhaka", "upazila": "Savar", "union_or_ward": "Savar Pourashava", "bbs_geo_code": "302672"},
    "আশুলিয়া": {"division": "Dhaka", "district": "Dhaka", "upazila": "Savar", "union_or_ward": "Ashulia Union", "bbs_geo_code": "302672"},
    "ashulia": {"division": "Dhaka", "district": "Dhaka", "upazila": "Savar", "union_or_ward": "Ashulia Union", "bbs_geo_code": "302672"},
    "সিলেট": {"division": "Sylhet", "district": "Sylhet", "upazila": "Sylhet Sadar", "union_or_ward": "Sylhet City Corp", "bbs_geo_code": "6091"},
    "sylhet": {"division": "Sylhet", "district": "Sylhet", "upazila": "Sylhet Sadar", "union_or_ward": "Sylhet City Corp", "bbs_geo_code": "6091"},
    "ফেনী": {"division": "Chattogram", "district": "Feni", "upazila": "Feni Sadar", "union_or_ward": "Feni Pourashava", "bbs_geo_code": "2030"},
    "feni": {"division": "Chattogram", "district": "Feni", "upazila": "Feni Sadar", "union_or_ward": "Feni Pourashava", "bbs_geo_code": "2030"},
    "চট্টগ্রাম": {"division": "Chattogram", "district": "Chattogram", "upazila": "Chattogram Metro", "union_or_ward": "CCC Ward 14", "bbs_geo_code": "2015"},
    "chattogram": {"division": "Chattogram", "district": "Chattogram", "upazila": "Chattogram Metro", "union_or_ward": "CCC Ward 14", "bbs_geo_code": "2015"},
    "বরিশাল": {"division": "Barishal", "district": "Barishal", "upazila": "Barishal Sadar", "union_or_ward": "BCC Ward 1", "bbs_geo_code": "1006"},
    "barishal": {"division": "Barishal", "district": "Barishal", "upazila": "Barishal Sadar", "union_or_ward": "BCC Ward 1", "bbs_geo_code": "1006"},
}

LIFE_SAFETY_P1_KEYWORDS: tuple[str, ...] = (
    "trapped on roof",
    "medical emergency",
    "embankment breach",
    "live wire in water",
    "ছাদে আটকা",
    "বাঁধ ভেঙে",
    "তার ছিঁড়ে পানিতে",
    "জরুরি চিকিৎসা",
    "পানিতে বিদ্যুতের তার",
    "drowning",
    "ভবন ধসে",
)


class BanglaGeoNERPipeline:
    """Extracts administrative hierarchy, road ownership hints, and P1 rescue triggers."""

    def analyze(self, *, text_bn: str = "", text_en: str = "") -> dict[str, Any]:
        combined = f"{text_bn} {text_en}".lower()
        entities: list[str] = []
        primary = {"division": "", "district": "", "upazila": "", "union_or_ward": "", "bbs_geo_code": ""}

        for token, info in GAZETTEER.items():
            if token in combined:
                if info["upazila"] not in entities:
                    entities.append(info["upazila"])
                if not primary["bbs_geo_code"]:
                    primary = info

        # Infrastructure road ownership hinting
        road_hint = ""
        if any(k in combined for k in ("national highway", "highway", "মহাসড়ক", "rhd", "সওজ", "n1")):
            road_hint = "RHD_NATIONAL_HIGHWAY"
        elif any(k in combined for k in ("upazila road", "rural road", "union road", "উপজেলা সড়ক", "lged", "এলজিইডি")):
            road_hint = "LGED_RURAL_ROAD"
        elif any(k in combined for k in ("dncc", "dscc", "city corp", "ward", "রাস্তা", "road")):
            road_hint = "CITY_CORP_ROAD"

        matched_rescue = [kw for kw in LIFE_SAFETY_P1_KEYWORDS if kw in combined]
        return {
            **primary,
            "road_ownership_hint": road_hint,
            "extracted_entities": entities,
            "is_life_safety_p1": bool(matched_rescue),
            "matched_rescue_keywords": matched_rescue,
        }
