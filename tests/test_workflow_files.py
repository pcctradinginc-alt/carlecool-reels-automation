"""GitHub rejects workflow files with duplicate keys; PyYAML silently accepts them.

zernio-preflight.yml had `name:` twice and failed on every push without a log.
"""
from pathlib import Path

import pytest
import yaml


class StrictLoader(yaml.SafeLoader):
    pass


def _no_duplicates(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise ValueError(f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicates)
WORKFLOWS = sorted(Path(".github/workflows").glob("*.yml"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=[p.name for p in WORKFLOWS])
def test_workflow_has_no_duplicate_keys(path):
    yaml.load(path.read_text(encoding="utf-8"), Loader=StrictLoader)
