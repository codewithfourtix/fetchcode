from packageurl import PackageURL

from fetchcode import package_util
from fetchcode.packagedcode_models import Package


def test_github_package_without_release_date(monkeypatch):
    monkeypatch.setattr(
        package_util.utils, "fetch_github_tags_gql", lambda purl: [("v1.2.3", None)]
    )
    purl = PackageURL("github", "example", "project")
    packages = list(package_util.get_github_packages(purl, None, None, Package(**purl.to_dict())))
    assert len(packages) == 1
    assert packages[0].version == "1.2.3"
    assert packages[0].release_date is None
