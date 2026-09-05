from fetchcode.package_util import get_cocoapod_tags


def test_cocoapod_tags_skip_packages_with_same_prefix(monkeypatch):
    monkeypatch.setattr(
        "fetchcode.utils.get_text_response", lambda url: "FooBar/9.0\nFoo/1.0/2.0\n"
    )
    assert get_cocoapod_tags("https://example.com/versions", "Foo") == ["1.0", "2.0"]


def test_cocoapod_tags_return_none_when_only_prefix_matches(monkeypatch):
    monkeypatch.setattr("fetchcode.utils.get_text_response", lambda url: "FooBar/9.0\n")
    assert get_cocoapod_tags("https://example.com/versions", "Foo") is None
