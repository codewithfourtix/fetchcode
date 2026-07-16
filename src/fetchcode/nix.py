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
import shutil
import subprocess
import sys
from urllib.parse import urlparse

import requests
from packageurl import PackageURL
from packageurl.contrib.purl2url import build_hackage_download_url
from packageurl.contrib.purl2url import get_repo_download_url_by_package_type

from fetchcode import fetch_json_response


class Nix:
    """
    Handle Nix Package URL (PURL) resolution and download URL retrieval.
    """

    purl_pattern = "pkg:nix/nixpkgs/.*"

    @classmethod
    def get_package_data(cls, purl):
        """
        Fetch package data from https://search.devbox.sh/.
        """
        parsed_purl = PackageURL.from_string(purl)

        api_url = f"https://search.devbox.sh/v2/pkg?name={parsed_purl.name}"
        try:
            return fetch_json_response(api_url)
        except Exception as e:
            print(f"Failed to fetch package data for {purl}: {e}")
            return None

    @classmethod
    def get_download_url(cls, purl):
        """
        Get a single direct download URL of a system-specific binary.
        """
        purl_data = PackageURL.from_string(purl)
        have_nix = False

        if shutil.which("nix") is not None:
            have_nix = True

        namespace = purl_data.namespace
        # We will only work with the official nixpkgs repository, at least
        # for now.
        if not namespace or namespace.lower() != 'nixpkgs':
            raise Exception(
                "Only official nixpkgs repository is supported (i.e. namespace=nixpkgs)."
            )
        name = purl_data.name
        version = purl_data.version
        qualifiers = purl_data.qualifiers or {}

        if "system" in qualifiers:
            system = qualifiers.get("system", "")
        else:
            raise Exception(
                "The 'system' qualifier is required to resolve system-specific binaries."
            )
        commit_hash = qualifiers.get("commit", "")
        # Default 'out' if no output is defined
        output = qualifiers.get("output", "out")

        data = cls.get_package_data(purl)
        path = ""

        if data:
            path = get_nix_store_path(data, system, output, commit_hash, version)
        if not data or not path:
            if have_nix and commit_hash:
                path = get_nix_store_path_with_nix(name, system, output, commit_hash)
                clean_garbage()

        if path:
            return get_nix_download_url(path)
        else:
            return None

    @classmethod
    def get_upstream_src_download_url(cls, purl):
        """
        Get a single upstream direct source download URL.
        """
        # Nix does not host a central repository of source code packages.
        # Instead, each package definition (.nix file such as default.nix
        # or package.nix) specifies how to fetch the upstream source (e.g.
        # from GitHub, GitLab, SourceForge etc.) and then applies any
        # patches or configuration during the build phases. The sources
        # fetched are always the original, unmodified upstream archives.
        # There is no direct URL for the patched or configured sources.
        # This function is intended to return the direct upstream
        # source download_url. Note that this may not represent the
        # complete build input, since patches and configuration are applied
        # later in the Nix build process.
        purl_data = PackageURL.from_string(purl)
        have_nix = False
        download_url = None

        if shutil.which("nix") is not None:
            have_nix = True

        namespace = purl_data.namespace
        # We will only work with the official nixpkgs repository, at least
        # for now.
        if not namespace or namespace.lower() != 'nixpkgs':
            raise Exception(
                "Only official nixpkgs repository is supported (i.e. namespace=nixpkgs)."
            )
        name = purl_data.name
        version = purl_data.version

        data = cls.get_package_data(purl)

        if data:
            download_url = construct_url_based_on_homepage_url(purl_data, data)

        if not download_url and have_nix:
            download_url = retrieve_src_download_url_with_nix(name, version)
            if not download_url and data and version:
                commit_hash = get_commit_hash(data, version)
                if commit_hash:
                    download_url = retrieve_src_download_url_with_nix(name, version, commit_hash)

        if not download_url and not have_nix:
            print("Install `nix` and re-run to let `nix` determine the download URL.")

        if have_nix:
            clean_garbage()

        return download_url


def get_nix_store_path(data, system, output, commit_hash=None, version=None):
    """
    Find and return the store path (/nix/store/<path>) based on the qualifiers
    """
    releases = data.get("releases") or []

    # Filter the list for specific version (no commit_hash provided)
    if not commit_hash and version:
        releases = [r for r in releases if r.get("version") == version]

    for release in releases:
        release_version = release.get("version", "")
        if version and release_version != version:
            continue
        for platform in release.get("platforms", []):
            if platform.get("system") != system:
                continue
            if commit_hash and platform.get("commit_hash") != commit_hash:
                continue
            for out in platform.get("outputs", []):
                if out.get("name") == output:
                    return out.get("path")
    return None


def get_nix_store_path_with_nix(name, system, output, commit_hash):
    """
    Find and return the store path (/nix/store/<path>) based on the
    qualifiers using 'nix'
    """
    system_config = f'system = "{system}";' if system else ""
    output_modifier = f".{output}" if output else ""

    nix_expression = (
        f'(import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/{commit_hash}.tar.gz") '
        f"{{ {system_config} }}).{name}{output_modifier}.outPath"
    )

    cmd = ["nix-instantiate", "--eval", "--raw", "-E", nix_expression]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error evaluating attribute for package '{name}'", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        return None


def retrieve_src_download_url_with_nix(name, version=None, commit_hash=None):
    """
    Find and return the source download url using 'nix'
    """
    info = get_src_info(name, commit_hash)
    urls = info.get("urls", [])

    download_url = None
    # We don't need to check for version if we have the commit_hash
    if commit_hash:
        for url in urls:
            if url.startswith("mirror:"):
                download_url = convert_mirror_url(url)
            else:
                if verify_url_existence(url):
                    download_url = url
            if download_url:
                break
    else:
        if not version:
            for url in urls:
                if url.startswith("mirror:"):
                    download_url = convert_mirror_url(url)
                else:
                    if verify_url_existence(url):
                        download_url = url
                if download_url:
                    break
        else:
            # Attempt to replace the fetched version with the input version
            # and validate that the URL exists. Return None if the URL is
            # invalid.
            fetched_latest_version = info.get("version")
            for url in urls:
                if url.startswith("mirror:"):
                    converted_url = convert_mirror_url(url)
                    if converted_url and fetched_latest_version:
                        updated_version_url = version.join(converted_url.rsplit(fetched_latest_version, 1))
                    else:
                        continue
                else:
                    if not fetched_latest_version:
                        continue
                    updated_version_url = version.join(url.rsplit(fetched_latest_version, 1))

                if verify_url_existence(updated_version_url):
                    download_url = updated_version_url
                    break

    return download_url


def get_src_info(attr_path, commit_hash=None):
    """
    Use the `nix-instantiate` command together with the nix_expression to
    retrieve the package’s version and download URL. Return a dictionary
    with "version" and "urls" keys.
    """
    # Determine the repository entry point definition
    if commit_hash:
        nixpkgs_import = (
            'import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/'
            f'{commit_hash}.tar.gz") {{}}'
        )
    else:
        nixpkgs_import = "import <nixpkgs> {}"

    nix_expression = f"""
    let
        pkg = ({nixpkgs_import}).{attr_path};
        extract_urls = src:
        if builtins.hasAttr "url" src then [src.url]
        else if builtins.hasAttr "urls" src then src.urls
        else if builtins.hasAttr "src" src then extract_urls src.src
        else [];
    in
        {{
            version = if builtins.hasAttr "version" pkg then pkg.version else null;
            urls = if builtins.hasAttr "src" pkg then extract_urls pkg.src else [];
        }}
    """
    cmd = [
        "nix-instantiate",
        "--eval",
        "--json",
        "--strict",
        "-E",
        nix_expression,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"Error evaluating attribute '{attr_path}':", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        return {"version": None, "urls": []}


def construct_url_based_on_homepage_url(input_purl, data):
    """
    Determine and return the download url based on the homepage and
    version
    """
    homepage_url = data.get("homepage_url", None)
    if not homepage_url:
        return None

    netloc = ""
    # Get the latest version if no version is provided
    if not input_purl.version:
        releases = data.get("releases")
        if not releases:
            return None
        version = releases[0].get("version")
    else:
        version = input_purl.version

    if not version:
        return None

    netloc, namespace, name = get_url_netloc_namespace_and_name(homepage_url)
    if netloc.endswith("github.io"):
        github_page_url = github_pages_to_repo(homepage_url)
        if github_page_url:
            netloc, namespace, name = get_url_netloc_namespace_and_name(github_page_url)

    if netloc in ("github.com", "gitlab.com", "bitbucket.org"):
        if netloc.endswith(".com"):
            package_type = netloc.removesuffix(".com")
            clarified_version = clarify_version_tag(package_type, namespace, name, version)
            if clarified_version:
                version = clarified_version
        elif netloc.endswith(".org"):
            package_type = netloc.removesuffix(".org")
        # There is an issue where the version may have a 'v' prefix, which
        # makes the constructed download URL invalid. For example, in
        # https://github.com/containers/aardvark-dns/, the constructed
        # download_url is
        # https://github.com/containers/aardvark-dns/archive/1.8.0.tar.gz, but
        # this returns a 404 because the actual download URL should be
        # https://github.com/containers/aardvark-dns/archive/v1.8.0.tar.gz.

        # Users are responsible for providing the correct version string
        # (including any 'v' prefix). However, from a mining situation, the
        # source data we collect may omit the prefix, so we need to handle that
        # case. For example, versions from
        # https://search.devbox.sh/v2/pkg?name=CuboCore.corepins do not include
        # the 'v' prefix, but the actual versions from the download site
        # include it in the tag field:
        # https://gitlab.com/api/v4/projects/cubocore%2Fcoreapps%2Fcorepins/repository/tags

        # There are also cases that use other prefix such as release-{version}
        # See https://search.devbox.sh/v2/pkg?name=SDL2_mixer where one of
        # the versions is 2.8.2 while the tag from the github is
        # release-2.8.2
        # (https://github.com/libsdl-org/SDL_mixer/releases/tag/release-2.8.2)

        # We want to validate whether the returned download URL is
        # accessible. If it is not, insert a common prefix and try to
        # validate again.
        common_prefixes = ["v", "V", "v-", "V-", "release-", "RELEASE-"]
        download_url = get_repo_download_url_by_package_type(
            type=package_type, namespace=namespace, name=name, version=version
        )
        if not verify_url_existence(download_url):
            for prefix in common_prefixes:
                prefix_version = prefix + version
                download_url = get_repo_download_url_by_package_type(
                    type=package_type, namespace=namespace, name=name, version=prefix_version
                )
                if verify_url_existence(download_url):
                    return download_url
        else:
            return download_url
    elif netloc == "hackage.haskell.org":
        pname = name.strip("haskellPackages.")
        purl = "pkg:hackage/" + pname + "@" + version
        download_url = build_hackage_download_url(purl)
        if verify_url_existence(download_url):
            return download_url
    else:
        candidates = []
        # CRAN (R Packages)
        if netloc == "cran.r-project.org":
            candidates = [
                f"https://cran.r-project.org/src/contrib/{name}_{version}.tar.gz",
                f"https://cran.r-project.org/src/contrib/Archive/{name}/{name}_{version}.tar.gz",
            ]
        # PyPI (Python Packages)
        elif netloc == "pypi.org" or netloc == "pypi.python.org":
            first_letter = name[0]
            candidates = [
                f"https://files.pythonhosted.org/packages/source/"
                f"{first_letter}/{name}/{name}-{version}.tar.gz"
            ]
        # Bioconductor (R Biology Packages)
        elif netloc == "bioconductor.org":
            candidates = [
                f"https://bioconductor.org/packages/release/bioc/"
                f"src/contrib/{name}_{version}.tar.gz"
            ]

        # Test candidates to verify existence
        for url in candidates:
            if verify_url_existence(url):
                return url
    return None


def github_pages_to_repo(url):
    """
    Try to map a GitHub Pages URL (https://{org}.github.io/{name}/)
    to its corresponding GitHub repository (https://github.com/{org}/{name}).
    Returns the repo URL if it exists, otherwise None.
    """
    parsed = urlparse(url)
    host = parsed.netloc
    parts = parsed.path.strip("/").split("/")

    # Only handle {org}.github.io/{name} pattern
    if not host.endswith(".github.io") or len(parts) < 1:
        return None

    org = host.replace(".github.io", "")
    name = parts[0]

    repo = f"https://github.com/{org}/{name}"

    # Verify existence via GitHub API
    api_url = f"https://api.github.com/repos/{org}/{name}"
    try:
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            return repo
    except requests.RequestException:
        return None

    return None


def get_url_netloc_namespace_and_name(url):
    """
    Extract netloc, namespace, and name from a URL path.
    - The last path component is considered the name.
    - Everything between netloc and name is considered the namespace.
    """
    parsed = urlparse(url)
    netloc = parsed.netloc
    parts = parsed.path.strip("/").split("/")

    if not parts or parts == [""]:
        return netloc, None, None

    name = parts[-1]
    namespace = "/".join(parts[:-1]) if len(parts) > 1 else None

    return netloc, namespace, name


def get_mirrors_map():
    """
    Get the mirror map from mirrors.nix and export it in JSON format.
    """
    nix_expression = (
        "builtins.removeAttrs "
        "(import <nixpkgs/pkgs/build-support/fetchurl/mirrors.nix>) "
        '[ "hashedMirrors" ]'
    )

    cmd = [
        "nix-instantiate",
        "--eval",
        "--json",
        "--strict",
        "-E",
        nix_expression,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print("Error exporting mirrors mapping:", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        return {}


def convert_mirror_url(url):
    """
    Convert a mirror:// URL into its actual direct URL
    """
    from urllib.parse import urljoin

    mirror_map = get_mirrors_map()
    mirror = url[len("mirror://") :]
    # Split by "/" to separate components: the first is the mirror_type,
    # and the rest form the path.
    # For example, "mirror://sourceforge/enlightenment/imlib2-1.12.6.tar.xz":
    # mirror_type = "sourceforge"
    # path = "enlightenment/imlib2-1.12.6.tar.xz"
    mirror_type = mirror.split("/")[0]
    path = "/".join(mirror.split("/")[1:])
    mirror_urls = mirror_map.get(mirror_type, [])
    for mirror_url in mirror_urls:
        converted_url = urljoin(mirror_url, path)
        if verify_url_existence(converted_url):
            return converted_url
    return None


def get_commit_hash(data, version):
    """
    Get the commit hash.
    """
    releases = data.get("releases") or []
    for release in releases:
        if release.get("version") == version:
            platforms = release.get("platforms") or []
            if platforms:
                return platforms[0].get("commit_hash")
    return None


def get_nix_download_url(path):
    """
    Construct a download url from cache.nixos.org based on the /nix/store/
    path
    """
    base_name = path.rstrip("/").split("/")[-1]
    narinfo_hash = base_name.split("-")[0]

    narinfo_url = f"https://cache.nixos.org/{narinfo_hash}.narinfo"
    url_path = get_narinfo_url(narinfo_url)

    if not url_path:
        return None

    return f"https://cache.nixos.org/{url_path}"


def get_narinfo_url(narinfo_url):
    """
    Visit the narinfo url, parsed and return the URL value
    """
    # Fetch the narinfo file
    try:
        response = requests.get(narinfo_url, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        return None

    # Parse line by line
    for line in response.text.splitlines():
        if line.startswith("URL:"):
            # Strip off "URL:" and any whitespace
            return line.split(":", 1)[1].strip()

    return None


def verify_url_existence(url):
    """
    Performs a fast HTTP HEAD request to check if a generated URL is valid.
    """
    try:
        response = requests.head(url, allow_redirects=True, timeout=10)
        if response.status_code == 200:
            return True
        elif response.status_code in (403, 429, 409):  # forbidden, rate limit, conflict
            return True  # resource exists but not accessible
        else:
            return False
    except Exception:
        return False


def clarify_version_tag(repo_type, namespace, name, version):
    """
    Use github/gitlan API to verify the version tag
    """
    normalized_version = normalize_string(version)
    tags = []
    try:
        if repo_type == "github":
            url = f"https://api.github.com/repos/{namespace}/{name}/tags"

        elif repo_type == "gitlab":
            ns = namespace if namespace else ""
            project_path = f"{ns}/{name}".strip("/").replace("/", "%2F")
            url = f"https://gitlab.com/api/v4/projects/{project_path}/repository/tags"
        else:
            return None
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        tags = response.json()
    except (requests.RequestException, ValueError):
        return None

    for tag in tags:
        tag_name = tag.get("name", "")
        normalized_tag = normalize_string(tag_name)
        if normalized_version == normalized_tag:
            return tag_name
    return None


def normalize_string(version_string):
    """
    Normalize common prefix version string
    """
    for prefix in ("release-", "RELEASE-", "v", "V"):
        if version_string.startswith(prefix):
            return version_string[len(prefix):]
    return version_string


def clean_garbage():
    """
    Delete all unreferenced downloaded tarballs and evaluation caches
    """
    try:
        subprocess.run(["nix-store", "--gc"], capture_output=True)
    except FileNotFoundError:
        pass
