"""Vietnamese second-person address forms.

Lives in the neutral shared layer so both the prompt assembly
(``services.lead.normalizers``) and the graph runner (deterministic-reply
normalization) resolve the same mapping without a graph → services import.
"""

from __future__ import annotations

# ``gender`` is deliberately never probed for ("giới tính của bạn?" is a rude
# opener), only received — from the candidate stating it, or from the provider
# profile when the app has been granted access to it.
_ADDRESS_FORMS = {"male": "anh", "female": "chị"}
NEUTRAL_ADDRESS_FORM = "anh/chị"


def address_form(gender: str | None) -> str:
    """Return how the bot should address a candidate of this gender.

    Unknown, blank, and unrecognised values all resolve to the neutral
    "anh/chị", which is ordinary polite Vietnamese rather than a visible
    fallback — guessing wrong reads far worse than staying neutral.
    """
    return _ADDRESS_FORMS.get(str(gender or "").strip().lower(), NEUTRAL_ADDRESS_FORM)


__all__ = ["NEUTRAL_ADDRESS_FORM", "address_form"]
