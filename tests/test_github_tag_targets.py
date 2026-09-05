import pytest

from fetchcode import utils


@pytest.mark.parametrize("target", [{}, {"target": {}}, {"target": None}])
def test_tags_without_commit_targets(monkeypatch, target):
    monkeypatch.setattr(
        utils, "fetch_github_tag_nodes", lambda purl: [{"name": "v1", "target": target}]
    )
    assert list(utils.fetch_github_tags_gql(None)) == [("v1", None)]
