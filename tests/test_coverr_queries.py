"""Coverr search terms reflect its real API vocabulary, not full generative prompts."""
from carlecool.video import _coverr_search_phrase

def test_detailed_shot_prompts_get_three_usable_broad_coverr_terms():
    assert _coverr_search_phrase("skateboarding night city") == "skateboarding"
    assert _coverr_search_phrase("minimalist white room natural wood sunlight") == "beach"
    assert _coverr_search_phrase("palm tree sunset silhouette super 8 film") == "sunset"
    assert _coverr_search_phrase("vintage California motel") == "road"
    assert _coverr_search_phrase("neon purple city night") == "city"
