# fetchcode is a free software tool from nexB Inc. and others.
# Visit https://github.com/aboutcode-org/fetchcode for support and download.
#
# Copyright (c) nexB Inc. and others. All rights reserved.
# http://nexb.com and http://aboutcode.org
#
# This software is licensed under the Apache License version 2.0.
#
# You may not use this software except in compliance with the License.
# You may obtain a copy of the License at:
# http://apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fetchcode import nix
from fetchcode.nix import Nix

from packageurl import PackageURL

DATA_DIR = Path(__file__).parent / "data" / "nix"


def load_fixture(filename):
    with open(DATA_DIR / filename) as f:
        return json.load(f)


HSTR_RESPONSE = load_fixture("hstr.json")


def mock_fetch_json_response(url):
    """Return appropriate fixture based on request URL."""
    if url == "https://search.devbox.sh/v2/pkg?name=hstr":
        return HSTR_RESPONSE
    raise ValueError(f"Unexpected URL: {url}")


@patch("fetchcode.nix.fetch_json_response", side_effect=mock_fetch_json_response)
class TestNix(unittest.TestCase):
    def test_get_package_data(self, mock_fetch):
        purl = "pkg:nix/nixpkgs/hstr"
        result = Nix.get_package_data(purl)
        self.assertEqual(result["name"], "hstr")
        self.assertEqual(result["license"], "Apache-2.0")

    def test_get_nix_store_path_no_version(self, mock_fetch):
        purl = "pkg:nix/nixpkgs/hstr?system=x86_64-darwin"
        data = Nix.get_package_data(purl)
        system = "x86_64-darwin"
        output = "out"
        path = nix.get_nix_store_path(data, system, output)
        self.assertEqual(path, "/nix/store/r910fm5w0iqywcwflp9fx1dsiwf8kqnx-hstr-3.2")

    def test_get_nix_store_path_with_version(self, mock_fetch):
        purl = "pkg:nix/nixpkgs/hstr@3.1?system=x86_64-darwin"
        data = Nix.get_package_data(purl)
        system = "x86_64-darwin"
        output = "out"
        commit_hash = None
        version = "3.1"
        path = nix.get_nix_store_path(data, system, output, commit_hash, version)
        self.assertEqual(path, "/nix/store/vcildmf4v1jkci82ny3bfkhn6nlnf6nn-hstr-3.1")

    def test_get_nix_store_path_with_commit_hash(self, mock_fetch):
        purl = "pkg:nix/nixpkgs/hstr?system=x86_64-darwin%commit_hash=4a29d733e8a7d5b824c3d8c958a946a9867b3eb2"
        data = Nix.get_package_data(purl)
        system = "aarch64-darwin"
        output = "out"
        commit_hash = "4a29d733e8a7d5b824c3d8c958a946a9867b3eb2"
        version = None
        path = nix.get_nix_store_path(data, system, output, commit_hash, version)
        self.assertEqual(path, "/nix/store/vh8m653ps0n96lg68w90sf4xbi9n2nvx-hstr-3.1")

    def test_get_nix_store_path_version_commit_hash_not_match(self, mock_fetch):
        purl = "pkg:nix/nixpkgs/hstr@3.2?system=x86_64-darwin&commit_hash=4a29d733e8a7d5b824c3d8c958a946a9867b3eb2"
        data = Nix.get_package_data(purl)
        system = "aarch64-darwin"
        output = "out"
        commit_hash = "4a29d733e8a7d5b824c3d8c958a946a9867b3eb2"
        version = "3.2"
        path = nix.get_nix_store_path(data, system, output, commit_hash, version)
        self.assertEqual(path, None)

    def test_construct_url_based_on_homepage_url(self, mock_fetch):
        purl_str = "pkg:nix/nixpkgs/hstr?system=x86_64-darwin%commit_hash=4a29d733e8a7d5b824c3d8c958a946a9867b3eb2"
        purl = PackageURL.from_string(purl_str)
        data = Nix.get_package_data(purl_str)
        result = nix.construct_url_based_on_homepage_url(purl, data)
        self.assertEqual(result, "https://github.com/dvorka/hstr/archive/v3.2.tar.gz")

    def test_get_url_netloc_namespace_and_name(self, mock_fetch):
        url = "https://github.com/dvorka/hstr"
        netloc, namespace, name = nix.get_url_netloc_namespace_and_name(url)
        self.assertEqual(netloc, "github.com")
        self.assertEqual(namespace, "dvorka")
        self.assertEqual(name, "hstr")

    def test_get_commit_hash(self, mock_fetch):
        purl_str = "pkg:nix/nixpkgs/hstr@2.6?system=x86_64-darwin"
        data = Nix.get_package_data(purl_str)
        version = "2.6"
        commit_hash = nix.get_commit_hash(data, version)
        self.assertEqual(commit_hash, "96ba1c52e54e74c3197f4d43026b3f3d92e83ff9")

    def test_normalize_string(self, mock_fetch):
        version = nix.normalize_string("release-1.2.3")
        self.assertEqual(version, "1.2.3")

