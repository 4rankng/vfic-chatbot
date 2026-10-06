"""Candidate source attribution: capture, mapping, and the first-touch merge.

Two encodings reach ``conversations.attribution`` today:

* a Zalo prefill link — ``https://zalo.me/<oa>?text=%23<CODE>`` — puts the
  campaign's post code at the front of the candidate's first message;
* a Meta referral — ``message.referral`` on a Click-to-Messenger ad (carries the
  ad id and the ad's post id) or ``postback.referral`` on Get Started / m.me
  (carries our own ``ref`` only).

Neither may alter the text the bot sees, and a later touch may only fill keys
the first one left open.
"""

from __future__ import annotations

import pytest

from app.channels.providers.facebook_messenger import (
    FacebookMessengerNormalizer,
    attribution_from_referral,
)
from app.services.conversation._shared import merge_attribution
from app.services.webhook import ZaloWebhookService

_AD_REFERRAL = {
    "ref": "BaiTuyenDung-01",
    "ad_id": "1234567890",
    "source": "ADS",
    "type": "OPEN_THREAD",
    "ads_context_data": {
        "ad_title": "Tuyển dụng LG",
        "photo_url": "https://example.invalid/p.jpg",
        "post_id": "111_222",
        "product_id": "333",
    },
}


def _bot_payload(text: str) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": "m-1",
            "chat": {"id": "candidate-chat"},
            "from": {"name": "Nguyen Van A"},
            "text": text,
        },
    }


def _messenger_payload(message: dict) -> dict:
    return {
        "entry": [
            {
                "id": "page-1",
                "messaging": [
                    {
                        "sender": {"id": "psid-1"},
                        "recipient": {"id": "page-1"},
                        "timestamp": 1458692752478,
                        "message": message,
                    }
                ],
            }
        ]
    }


# --- Zalo prefill link ------------------------------------------------------


def test_prefill_code_is_captured_and_the_text_is_left_untouched() -> None:
    norm = ZaloWebhookService.normalize_bot(
        _bot_payload("#BV1026 muon hoi viec lam")
    )

    assert norm is not None
    assert norm.attribution == {"kind": "post_link", "post_code": "BV1026"}
    # The code is recorded, never stripped — the turn sees the candidate's text.
    assert norm.user_text == "#BV1026 muon hoi viec lam"


def test_ordinary_first_message_carries_no_attribution() -> None:
    for text in (
        "xin chao",
        # Not leading: a hashtag inside a sentence is conversation.
        "minh thich #BV1026 a",
        # Too short to be a code — a stray "#1" must never become a source.
        "#1 muon ung tuyen",
        # Right shape but no digit: an ASCII hashtag word, not a campaign code.
        "#tuyen dung",
        "#viec lam",
    ):
        norm = ZaloWebhookService.normalize_bot(_bot_payload(text))
        assert norm is not None, text
        assert norm.attribution is None, text


def test_prefill_code_accepted_with_trailing_punctuation() -> None:
    norm = ZaloWebhookService.normalize_bot(_bot_payload("#BV1026, minh muon ung tuyen"))

    assert norm is not None
    assert norm.attribution == {"kind": "post_link", "post_code": "BV1026"}


def test_oa_event_path_uses_the_same_code_rule() -> None:
    event_payload = {
        "app_id": "app-1",
        "event_name": "user_send_text",
        "oa_id": "oa-1",
        "sender": {"id": "user-1"},
        "recipient": {"id": "oa-1"},
        "message": {"text": "#TD1026 xin loi cho minh hoi", "msg_id": "96d3"},
        "timestamp": "154390853474",
    }
    norm = ZaloWebhookService.normalize_oa(event_payload)

    assert norm is not None
    assert norm.attribution == {"kind": "post_link", "post_code": "TD1026"}


# --- Messenger referral -----------------------------------------------------


def test_ad_referral_maps_ad_id_post_id_and_ad_title() -> None:
    # ad_title is the ad's own creative copy — the only human-written string in
    # the payload that says which dự án the ad is for, and the fallback when an
    # ad sets no custom ``ref``. Meta ships no campaign id here and no utm_*
    # parameters on a Messenger ad at all.
    assert attribution_from_referral(_AD_REFERRAL) == {
        "kind": "referral",
        "post_code": "BaiTuyenDung-01",
        "ad_id": "1234567890",
        "post_id": "111_222",
        "ad_title": "Tuyển dụng LG",
        "referral_source": "ADS",
    }


def test_blank_ad_title_is_omitted_rather_than_stored_empty() -> None:
    # Same truthy-string contract as every other field: an empty value must not
    # become a key, or downstream matchers would treat "" as a real title.
    attribution = attribution_from_referral(
        {
            "ref": "BaiTuyenDung-01",
            "ads_context_data": {"post_id": "111_222", "ad_title": "   "},
        }
    )

    assert attribution == {
        "kind": "referral",
        "post_code": "BaiTuyenDung-01",
        "post_id": "111_222",
    }


def test_referral_without_any_source_value_is_none() -> None:
    for referral in (None, "not-a-dict", {}, {"type": "OPEN_THREAD"}):
        assert attribution_from_referral(referral) is None


def test_shortlink_referral_keeps_only_the_code_and_source() -> None:
    assert attribution_from_referral(
        {"ref": "post_202610", "source": "SHORTLINK", "type": "OPEN_THREAD"}
    ) == {
        "kind": "referral",
        "post_code": "post_202610",
        "referral_source": "SHORTLINK",
    }


def test_normalizer_carries_the_message_referral_and_none_without_it() -> None:
    with_referral, ignored = FacebookMessengerNormalizer().normalize(
        _messenger_payload({"mid": "mid.1", "text": "xin tuyen dung", "referral": _AD_REFERRAL})
    )
    without_referral, _ = FacebookMessengerNormalizer().normalize(
        _messenger_payload({"mid": "mid.2", "text": "chao"})
    )

    assert len(with_referral) == 1
    assert with_referral[0].attribution == attribution_from_referral(_AD_REFERRAL)
    assert with_referral[0].text == "xin tuyen dung"  # text untouched
    assert without_referral[0].attribution is None
    assert ignored == {}


def test_get_started_postback_referral_is_extracted_for_stamping() -> None:
    payload = {
        "entry": [
            {
                "id": "page-1",
                "messaging": [
                    {
                        "sender": {"id": "psid-9"},
                        "recipient": {"id": "page-1"},
                        "postback": {
                            "mid": "m-9",
                            "title": "Get Started",
                            "payload": "GET_STARTED",
                            "referral": {
                                "ref": "post_202610",
                                "source": "SHORTLINK",
                                "type": "OPEN_THREAD",
                            },
                        },
                    },
                    {
                        "sender": {"id": "psid-8"},
                        "recipient": {"id": "page-1"},
                        "postback": {"mid": "m-8", "title": "Hi", "payload": "HI"},
                    },
                    # Another Page's event: one webhook can carry it, and it
                    # must never touch this deployment's data.
                    {
                        "sender": {"id": "psid-7"},
                        "recipient": {"id": "other-page"},
                        "postback": {
                            "mid": "m-7",
                            "title": "Get Started",
                            "payload": "GET_STARTED",
                            "referral": {"ref": "other_post", "source": "SHORTLINK"},
                        },
                    },
                ],
            }
        ]
    }

    assert FacebookMessengerNormalizer.referrals_from_payload(
        payload, page_id="page-1"
    ) == [
        (
            "psid-9",
            {"kind": "referral", "post_code": "post_202610", "referral_source": "SHORTLINK"},
        )
    ]


@pytest.mark.asyncio
async def test_page_subscription_requests_the_referral_field(
    monkeypatch,
) -> None:
    """Meta withholds a Click-to-Messenger ad's referral unless the Page is
    subscribed to ``messaging_referrals`` alongside ``messages`` — the ad id and
    ad post id behind a candidate's first message silently vanish without it.
    """
    from unittest.mock import AsyncMock

    from app.channels.providers import facebook_oauth as oauth

    post = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(oauth, "_bounded_post", post)

    await oauth.subscribe_app_to_page("page-1", "page-token")

    assert post.await_args.kwargs["json_body"] == {
        "subscribed_fields": "messages,messaging_postbacks,messaging_referrals"
    }


# --- First-touch merge ------------------------------------------------------


def test_no_existing_record_takes_the_incoming_touch_whole() -> None:
    incoming = {"kind": "post_link", "post_code": "BV1026"}
    assert merge_attribution(None, incoming) == incoming


def test_first_touch_wins_and_a_later_touch_only_fills_gaps() -> None:
    # Get Started arrived first (our ref, no Meta ids); the ad's ids ride the
    # first message — they must land without replacing the original record.
    first = {"kind": "referral", "post_code": "post_202610", "referral_source": "SHORTLINK"}
    later = {
        "kind": "referral",
        "post_code": "OTHER",
        "ad_id": "1234567890",
        "post_id": "111_222",
        "referral_source": "ADS",
    }

    assert merge_attribution(first, later) == {
        "kind": "referral",
        "post_code": "post_202610",
        "referral_source": "SHORTLINK",
        "ad_id": "1234567890",
        "post_id": "111_222",
    }


def test_blank_first_touch_values_stay_open_for_a_later_one() -> None:
    first = {"kind": "referral", "post_code": "", "referral_source": ""}
    later = {"kind": "referral", "post_code": "BV1026"}

    assert merge_attribution(first, later) == {
        "kind": "referral",
        "post_code": "BV1026",
        "referral_source": "",
    }
