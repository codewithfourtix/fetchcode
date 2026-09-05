import datetime

import pytest
from packageurl import PackageURL

from fetchcode import package_util
from fetchcode.packagedcode_models import Package


@pytest.mark.parametrize(
    "tag,expected", [("v1.2-dev", "1.2-dev"), ("v1_2_3+build_4", "1.2.3+build_4")]
)
def test_github_tag_version_normalization(monkeypatch, tag, expected):
    monkeypatch.setattr(
        package_util.utils,
        "fetch_github_tags_gql",
        lambda purl: [(tag, datetime.datetime(2026, 1, 1))],
    )
    purl = PackageURL("github", "example", "project")
    packages = list(package_util.get_github_packages(purl, None, None, Package(**purl.to_dict())))
    assert packages[0].version == expected
    assert packages[0].download_url.endswith(f"/{tag}.tar.gz")
