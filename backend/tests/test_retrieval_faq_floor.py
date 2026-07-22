"""Characterization of the FAQ pre-pass similarity floor.

Sheet-sourced FAQ chunks embed their full rendered record (label + id + question
+ answer + terms + tags), so a verbatim user query — which embeds as the bare
question — scores lower than a "clean" question embedding. The floor must sit in
the gap between non-FAQ drift and verbatim-FAQ matches, or the FAQ pre-pass
silently returns nothing (the original 0.70 regression that made every sheet FAQ
unretrievable). Measured on prod lg-display (post category-authority cutover):
non-FAQ queries top out at ~0.47; verbatim FAQ matches range 0.62-0.79 (weakest
0.621). These pin the floor inside that safe band so a future change can't
quietly re-raise it above the verbatim-match range.
"""

from __future__ import annotations

from app.services.retrieval import repository


def test_faq_similarity_floor_constant_leaves_headroom_for_verbatim_matches():
    # Pins the CLASS ATTRIBUTE value (not a live match_faq() retrieval run).
    floor = repository.RetrievalRepository.FAQ_SIMILARITY_FLOOR
    # Weakest measured verbatim FAQ match is 0.621; the floor must stay at or
    # below ~0.60 or every sheet-FAQ verbatim match is filtered out (the bug).
    assert floor <= 0.60, f"FAQ floor {floor} too high — filters verbatim matches"


def test_faq_similarity_floor_constant_stays_above_non_faq_drift():
    # Pins the CLASS ATTRIBUTE value (not a live match_faq() retrieval run).
    floor = repository.RetrievalRepository.FAQ_SIMILARITY_FLOOR
    # Non-FAQ queries top out at ~0.471; the floor must stay above that or the
    # FAQ pre-pass leaks curated answers into unrelated queries.
    assert floor > 0.48, f"FAQ floor {floor} too low — admits non-FAQ drift"
