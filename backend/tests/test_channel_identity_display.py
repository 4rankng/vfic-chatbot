"""ChannelIdentitySummaryOut display-channel derivation.

The TingTing employee-support OA and the Viet Phap OA share the zalo_oa
provider; account_key is masked before serialization, so the badge channel
must be derived from the raw value before masking (production incident: the
inbox TingTing filter rendered every row with the plain Zalo chip because the
masked key could never match "tingting").
"""

from types import SimpleNamespace
from uuid import uuid4

from app.schemas.contacts import ChannelIdentitySummaryOut


def test_tingting_account_displays_as_tingting_oa_and_stays_masked():
    row = SimpleNamespace(
        id=uuid4(), provider="zalo_oa", account_key="tingting", external_id="123456789"
    )

    out = ChannelIdentitySummaryOut.model_validate(row)

    assert out.display_channel == "tingting_oa"
    assert out.account_key is not None
    assert out.account_key != "tingting"
    assert out.account_key.endswith("ting")


def test_other_zalo_oa_account_keeps_the_provider_channel():
    row = SimpleNamespace(
        id=uuid4(),
        provider="zalo_oa",
        account_key="default:zalo_oa",
        external_id="123456789",
    )

    out = ChannelIdentitySummaryOut.model_validate(row)

    assert out.display_channel == "zalo_oa"


def test_single_account_channels_pass_through():
    for provider in ("zalo_bot", "facebook_messenger"):
        row = SimpleNamespace(
            id=uuid4(), provider=provider, account_key="acc-1", external_id=None
        )

        out = ChannelIdentitySummaryOut.model_validate(row)

        assert out.display_channel == provider


def test_dict_input_derives_display_channel_too():
    out = ChannelIdentitySummaryOut.model_validate(
        {
            "id": str(uuid4()),
            "provider": "zalo_oa",
            "account_key": "tingting",
            "external_id": None,
        }
    )

    assert out.display_channel == "tingting_oa"


def test_missing_provider_resolves_display_channel_to_none():
    out = ChannelIdentitySummaryOut.model_validate(
        {"id": str(uuid4()), "provider": "", "account_key": None}
    )

    assert out.display_channel is None
