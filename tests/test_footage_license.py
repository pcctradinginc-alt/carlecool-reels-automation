"""Publication must fail closed when stock source or Coverr credit is uncertain."""
import pytest

from carlecool.approve import validate_footage_rights


def sample(sources, caption=""):
    return {"footage_sources": sources, "caption": caption}


def test_free_coverr_api_requires_attribution():
    approved = sample([{"provider": "coverr", "id": "xyz"}],
                      "🎬 Footage by Coverr: https://coverr.co")
    validate_footage_rights(approved)
    with pytest.raises(RuntimeError, match="credit"):
        validate_footage_rights(sample(approved["footage_sources"], "© CarleCool"))


def test_owned_assets_do_not_require_coverr_credit():
    validate_footage_rights(sample([{"provider": "owned", "id": "mine"}]))


@pytest.mark.parametrize("sources", [[], None, [{}], [{"provider": "unknown"}], [42]])
def test_missing_or_unrecognised_provenance_stops_publication(sources):
    with pytest.raises(RuntimeError):
        validate_footage_rights(sample(sources))
