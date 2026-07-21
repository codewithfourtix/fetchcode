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
from unittest.mock import Mock
from unittest.mock import patch

from packageurl import PackageURL

from fetchcode import nix
from fetchcode.nix import Nix

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

    def test_get_nix_store_path_with_version(self, mock_fetch):
        purl = "pkg:nix/nixpkgs/hstr@3.1?system=x86_64-darwin"
        data = Nix.get_package_data(purl)
        system = "x86_64-darwin"
        output = "out"
        commit_hash = None
        version = "3.1"
        path = nix.get_nix_store_path(data, system, output, version, commit_hash)
        self.assertEqual(path, "/nix/store/vcildmf4v1jkci82ny3bfkhn6nlnf6nn-hstr-3.1")

    def test_get_nix_store_path_with_commit_hash(self, mock_fetch):
        purl = "pkg:nix/nixpkgs/hstr@3.1?system=x86_64-darwin&commit_hash=4a29d733e8a7d5b824c3d8c958a946a9867b3eb2"
        data = Nix.get_package_data(purl)
        system = "aarch64-darwin"
        output = "out"
        commit_hash = "4a29d733e8a7d5b824c3d8c958a946a9867b3eb2"
        version = "3.1"
        path = nix.get_nix_store_path(data, system, output, version, commit_hash)
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
        purl_str = "pkg:nix/nixpkgs/hstr?system=x86_64-darwin&commit=4a29d733e8a7d5b824c3d8c958a946a9867b3eb2"
        purl = PackageURL.from_string(purl_str)
        data = Nix.get_package_data(purl_str)
        result = nix.construct_url_based_on_homepage_url(purl, data)
        self.assertEqual(result, "https://github.com/dvorka/hstr/archive/3.1.tar.gz")

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

    @patch("subprocess.run")
    def test_get_nix_store_path_with_nix(self, mock_subproc_run, mock_fetch):
        mock_subproc_run.return_value.stdout = "/nix/store/111111111111111-test_package-1.0\n"

        result = nix.get_nix_store_path_with_nix(
            "test_package", "x86_64-linux", "out", "xxxxxxxxxxxxxxx"
        )

        self.assertEqual(result, "/nix/store/111111111111111-test_package-1.0")
        mock_subproc_run.assert_called_once()
        self.assertIn("nix-instantiate", mock_subproc_run.call_args[0][0])

    @patch("subprocess.run")
    def test_get_src_info(self, mock_subproc_run, mock_fetch):
        mock_subproc_run.return_value.stdout = (
            '{"version": "1.0.0", "urls": ["https://example.com/source.tar.gz"]}'
        )

        result = nix.get_src_info("python3Packages.requests", "xxxxxxxxxxxxxxx")

        self.assertEqual(result["version"], "1.0.0")
        self.assertEqual(result["urls"][0], "https://example.com/source.tar.gz")

    @patch("subprocess.run")
    def test_get_mirrors_map(self, mock_subproc_run, mock_fetch):
        mock_subproc_run.return_value.stdout = '{"sourceforge": ["https://sourceforge.net/"]}'

        result = nix.get_mirrors_map()
        self.assertIn("sourceforge", result)

    @patch("fetchcode.nix.get_mirrors_map")
    @patch("fetchcode.nix.verify_url_existence")
    def test_convert_mirror_url(self, mock_verify, mock_get_mirrors, mock_fetch):
        mock_get_mirrors.return_value = {"sourceforge": ["https://sourceforge.net/"]}
        mock_verify.return_value = True

        url = "mirror://sourceforge/test/sample-1.12.6.tar.xz"
        result = nix.convert_mirror_url(url)
        self.assertEqual(result, "https://sourceforge.net/test/sample-1.12.6.tar.xz")

    @patch("requests.get")
    def test_github_pages_to_repo(self, mock_get, mock_fetch):
        mock_get.return_value.status_code = 200

        url = "https://iovisor.github.io/bcc/"
        result = nix.github_pages_to_repo(url)
        self.assertEqual(result, "https://github.com/iovisor/bcc")

    @patch("requests.get")
    def test_get_narinfo_url(self, mock_get, mock_fetch):
        mock_get.return_value.text = "URL: 00000.nar.xz"

        result = nix.get_narinfo_url("https://cache.nixos.org/123.narinfo")
        self.assertEqual(result, "00000.nar.xz")

    @patch("fetchcode.nix.get_narinfo_url")
    def test_get_nix_download_url(self, mock_get_narinfo, mock_fetch):
        mock_get_narinfo.return_value = "nar/00000.nar.xz"

        result = nix.get_nix_download_url("/nix/store/1234567890abcdef-hstr-3.1")
        self.assertEqual(result, "https://cache.nixos.org/nar/00000.nar.xz")

    @patch("requests.get")
    def test_clarify_version_tag_github(self, mock_get, mock_fetch):
        # 404 for the first check (prefix ""), 200 for the second check (prefix "v")
        mock_get.side_effect = [Mock(status_code=404), Mock(status_code=200)]

        result = nix.clarify_version_tag("github", "project_namespace", "project_name", "1.0.0")

        self.assertEqual(result, "v1.0.0")

    def test_get_version_from_commit_hash(self, mock_fetch):
        mock_data = {
            "releases": [
                {
                    "version": "2.6",
                    "platforms": [
                        {
                            "system": "x86_64-darwin",
                            "commit_hash": "96ba1c52e54e74c3197f4d43026b3f3d92e83ff9",
                        }
                    ],
                }
            ]
        }

        version = nix.get_version_from_commit_hash(
            mock_data, "96ba1c52e54e74c3197f4d43026b3f3d92e83ff9"
        )
        self.assertEqual(version, "2.6")
