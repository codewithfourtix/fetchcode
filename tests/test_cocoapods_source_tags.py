import pytest
from packageurl import PackageURL

from fetchcode import package_util


@pytest.mark.parametrize("source_tag", ["v1.2.3", "release-1_2_3", None])
def test_cocoapods_source_tag_preserves_package_version(monkeypatch, source_tag):
    monkeypatch.setattr(
        package_util.utils,
        "get_response",
        lambda url: {
            "source": {"git": "https://github.com/example/Example.git", "tag": source_tag},
        },
    )
    purl = PackageURL(type="cocoapods", name="Example", version="1.2.3")
    package = package_util.construct_cocoapods_package(
        purl, "Example", "a/b/c", "https://cocoapods.org/pods/Example", None, None, "1.2.3"
    )
    assert package.version == "1.2.3"
    assert (
        package.download_url
        == f"https://github.com/example/Example/archive/refs/tags/{source_tag or '1.2.3'}.tar.gz"
    )
