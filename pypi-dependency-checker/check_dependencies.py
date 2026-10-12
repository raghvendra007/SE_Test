
import json
import re
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

PYPI_BASE_URL = "https://pypi.org/pypi"
REQUIREMENTS_FILE = "requirements.txt"


def fetch_pypi_json(url):
    """Fetch JSON from PyPI. Return (status, data)."""
    request = Request(
        url,
        headers={"User-Agent": "pypi-dependency-checker/1.0"},
    )

    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.load(response)

    except HTTPError as error:
        if error.code == 404:
            return 404, None
        raise RuntimeError(
            f"HTTP {error.code} while requesting {url}"
        ) from error

    except URLError as error:
        raise RuntimeError(f"Network error: {error}") from error


def parse_requirement(line):
    """Return (package, exact_version) or None."""
    line = line.strip()

    if not line or line.startswith("#"):
        return None

    if line.startswith("-") or line.startswith((".", "/", "git+")):
        return None

    # Remove inline comments and environment markers.
    line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
    line = line.split(";", maxsplit=1)[0].strip()

    match = re.match(
        r"^([A-Za-z0-9][A-Za-z0-9._-]*)"
        r"(?:\[[^\]]+\])?\s*(.*)$",
        line,
    )

    if not match:
        raise ValueError(f"Malformed requirement: {line}")

    name = match.group(1)
    remaining = match.group(2).strip()

    # Recognize exact pinned versions only.
    version_match = re.match(
        r"^==\s*([^\s,;#]+)\s*$",
        remaining,
    )

    # Accept common version specifiers, but don't treat them as exact pins.
    if remaining and not version_match:
        if not re.match(r"^(>=|<=|!=|~=|>|<|===)", remaining):
            raise ValueError(f"Unsupported requirement: {line}")

    version = version_match.group(1) if version_match else None

    return name, version


def parse_upload_time(value):
    """Parse PyPI's ISO 8601 upload timestamp."""
    if not value:
        return None

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main():
    dependencies = []
    packages_not_found = []
    versions_not_found = []
    valid_releases = []
    errors = []
    warnings = []

    try:
        with open(REQUIREMENTS_FILE, "r", encoding="utf-8") as file:
            for line_number, line in enumerate(file, start=1):
                try:
                    parsed = parse_requirement(line)
                    if parsed:
                        dependencies.append(parsed)
                except ValueError as error:
                    warnings.append(f"Line {line_number}: {error}")

    except OSError as error:
        print(f"Could not read {REQUIREMENTS_FILE}: {error}")
        return

    for name, version in dependencies:
        encoded_name = quote(name, safe="")

        try:
            # Check whether the package exists on PyPI.
            project_url = f"{PYPI_BASE_URL}/{encoded_name}/json"
            status, _ = fetch_pypi_json(project_url)

            if status == 404:
                packages_not_found.append(name)
                continue

            # Check exact versions only.
            if version is None:
                continue

            encoded_version = quote(version, safe="")
            release_url = (
                f"{PYPI_BASE_URL}/{encoded_name}/"
                f"{encoded_version}/json"
            )

            status, release_data = fetch_pypi_json(release_url)

            if status == 404:
                versions_not_found.append(f"{name}=={version}")
                continue

            # Use upload_time from the first file in urls.
            urls = release_data.get("urls", [])

            if not urls:
                warnings.append(
                    f"{name}=={version}: no files listed in urls"
                )
                continue

            upload_time = parse_upload_time(
                urls[0].get("upload_time")
            )

            if upload_time is None:
                warnings.append(
                    f"{name}=={version}: missing upload_time"
                )
                continue

            valid_releases.append(
                (upload_time, f"{name}=={version}")
            )

        except (RuntimeError, ValueError) as error:
            errors.append(f"{name}=={version or '*'}: {error}")

    # Print the report.
    print("\n========== PyPI Dependency Report ==========")

    print(f"1. Dependencies checked: {len(dependencies)}")

    print("\n2. Packages not on PyPI:")
    print(f"   {len(packages_not_found)}")

    print("\n3. Versions not on PyPI:")
    print(f"   {len(versions_not_found)}")

    print("\n4. Oldest pinned release:")
    if valid_releases:
        oldest = min(valid_releases, key=lambda item: item[0])
        print(f"   {oldest[1]}")
        print(f"   Uploaded: {oldest[0].isoformat()}")
    else:
        print("   None")

    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"   - {warning}")

    if errors:
        print("\nDependencies that could not be checked:")
        for error in errors:
            print(f"   - {error}")

    print("\n============================================")


if __name__ == "__main__":
    main()
