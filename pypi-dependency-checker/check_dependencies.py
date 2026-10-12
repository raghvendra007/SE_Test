
import json
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


PYPI_BASE_URL = "https://pypi.org/pypi"
REQUIREMENTS_FILE = "requirements.txt"


def fetch_pypi_json(url):
    """Return (status, JSON data). A 404 means the resource is missing."""
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
        raise

    except URLError as error:
        raise RuntimeError(f"Network error: {error}") from error


def parse_requirement(line):
    """Extract package name and an exact == pinned version, if present."""
    # Remove comments and surrounding whitespace.
    line = re.split(r"\s+#", line, maxsplit=1)[0].strip()

    if not line or line.startswith("#") or line.startswith("-"):
        return None

    # Remove environment markers, e.g. ; python_version >= "3.10"
    line = line.split(";", maxsplit=1)[0].strip()

    match = re.match(
        r"^([A-Za-z0-9][A-Za-z0-9._-]*)"
        r"(?:\[[^\]]+\])?\s*(.*)$",
        line,
    )

    if not match:
        print(f"WARNING: Could not parse: {line}")
        return None

    name = match.group(1)
    remaining = match.group(2)

    version_match = re.match(r"^==\s*([^\s,;#]+)", remaining)
    version = version_match.group(1) if version_match else None

    return name, version


def parse_upload_time(value):
    """Convert a PyPI upload timestamp to a comparable datetime."""
    if not value:
        return None

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main():
    dependencies = []
    packages_not_found = []
    versions_not_found = []
    valid_releases = []
    errors = []

    with open(REQUIREMENTS_FILE, "r", encoding="utf-8") as file:
        for line in file:
            parsed = parse_requirement(line)

            if parsed:
                dependencies.append(parsed)

    for name, version in dependencies:
        encoded_name = quote(name, safe="")
        project_url = f"{PYPI_BASE_URL}/{encoded_name}/json"

        try:
            # Check whether the package exists.
            status, project_data = fetch_pypi_json(project_url)

            if status == 404:
                packages_not_found.append(name)
                continue

            # Version ranges such as >=2.0 are not exact pins.
            if version is None:
                continue

            encoded_version = quote(version, safe="")
            release_url = (
                f"{PYPI_BASE_URL}/{encoded_name}/"
                f"{encoded_version}/json"
            )

            # Check whether this exact release exists.
            status, release_data = fetch_pypi_json(release_url)

            if status == 404:
                versions_not_found.append(f"{name}=={version}")
                continue

            # Use the upload_time of the first file in urls.
            urls = release_data.get("urls", [])

            if not urls:
                continue

            upload_time = parse_upload_time(urls[0].get("upload_time"))

            if upload_time is not None:
                valid_releases.append(
                    (upload_time, f"{name}=={version}")
                )

        except (URLError, RuntimeError, TimeoutError, ValueError) as error:
            errors.append(f"{name}: {error}")

    print("\n========== PyPI Dependency Report ==========")
    print(f"1. Dependencies checked: {len(dependencies)}")

    print("\n2. Packages not on PyPI:")
    print("\n".join(f"   - {p}" for p in packages_not_found)
          if packages_not_found else "   None")

    print("\n3. Versions not on PyPI:")
    print("\n".join(f"   - {v}" for v in versions_not_found)
          if versions_not_found else "   None")

    print("\n4. Oldest pinned release:")
    if valid_releases:
        oldest = min(valid_releases, key=lambda item: item[0])
        print(f"   {oldest[1]}")
        print(f"   Uploaded: {oldest[0].isoformat()}")
    else:
        print("   No valid pinned releases with upload timestamps.")

    if errors:
        print("\nRequests that could not be checked:")
        for error in errors:
            print(f"   - {error}")

    print("\n============================================")


if __name__ == "__main__":
    main()
