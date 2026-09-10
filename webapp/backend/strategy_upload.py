"""Manifest parsing and validation for Stage E multi-file strategy uploads
(architecture doc Section 5.7).

This module ONLY parses, validates, and stores an uploaded project — it never
executes any of it. Actual execution of uploaded strategies waits on Phase 4's
container-based sandbox (see PHASE2_BUILD_SPEC.md Section 7); Stage D's
subprocess-only isolation (sandbox.py) is not a strong enough guarantee for code
that isn't one of the two trusted, built-in reference strategies.
"""

import io
import json
import re
import zipfile
from pathlib import Path

MANIFEST_FILENAME = "manifest.json"
REQUIRED_MANIFEST_KEYS = ("entry_point", "language")
SUPPORTED_LANGUAGES = ("python",)  # MQL/Pine are future translation targets (Section 5.3/5.4), not built yet
# Deliberately small allowlist (Section 5.7: "dependency installation is a security
# surface") — matches backtest-core's own dependencies. Expand only on purpose.
ALLOWED_DEPENDENCIES = {"numpy", "pandas"}
ENTRY_POINT_PATTERN = re.compile(r"^[\w./-]+\.py:[A-Za-z_][A-Za-z0-9_]*$")
MAX_ZIP_SIZE_BYTES = 5 * 1024 * 1024


class ManifestError(ValueError):
    pass


def _package_name(requirement: str) -> str:
    """Strips a version specifier off a requirements.txt-style string, e.g.
    'numpy>=1.26' -> 'numpy'."""
    return re.split(r"[<>=! ]", requirement.strip())[0].lower()


def parse_and_validate_zip(zip_bytes: bytes) -> tuple[dict, zipfile.ZipFile]:
    """Extracts and validates the manifest from a project zip. Returns the parsed
    manifest dict and the open ZipFile (caller extracts and closes it). Raises
    ManifestError with a human-readable message for any problem — never raises a
    raw zipfile/json exception the caller would have to translate."""
    if len(zip_bytes) > MAX_ZIP_SIZE_BYTES:
        raise ManifestError(f"project zip exceeds the {MAX_ZIP_SIZE_BYTES // 1024}KB limit")

    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ManifestError("not a valid zip file") from exc

    names = zf.namelist()
    if MANIFEST_FILENAME not in names:
        raise ManifestError(f"missing {MANIFEST_FILENAME} at the project root")

    try:
        manifest = json.loads(zf.read(MANIFEST_FILENAME))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{MANIFEST_FILENAME} is not valid JSON: {exc}") from exc

    missing = [key for key in REQUIRED_MANIFEST_KEYS if key not in manifest]
    if missing:
        raise ManifestError(f"manifest missing required key(s): {', '.join(missing)}")

    if manifest["language"] not in SUPPORTED_LANGUAGES:
        raise ManifestError(
            f"language {manifest['language']!r} is not supported yet — only "
            f"{SUPPORTED_LANGUAGES} (MQL/Pine are future adapter work, Section 5.3/5.4)"
        )

    entry_point = manifest["entry_point"]
    if not ENTRY_POINT_PATTERN.match(entry_point):
        raise ManifestError(f"entry_point must look like 'file.py:ClassName', got {entry_point!r}")
    entry_file = entry_point.split(":")[0]
    if entry_file not in names:
        raise ManifestError(f"entry_point file {entry_file!r} not found in the uploaded project")

    dependencies = manifest.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise ManifestError("dependencies must be a list of package names")
    disallowed = [dep for dep in dependencies if _package_name(dep) not in ALLOWED_DEPENDENCIES]
    if disallowed:
        raise ManifestError(
            f"dependencies not on the allowlist: {disallowed} — allowed: {sorted(ALLOWED_DEPENDENCIES)}"
        )

    parameters = manifest.get("parameters", {})
    if not isinstance(parameters, dict):
        raise ManifestError("parameters must be an object/dict if present")

    return manifest, zf


def extract_project(zf: zipfile.ZipFile, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    zf.extractall(destination)
