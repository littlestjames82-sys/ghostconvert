"""Read a GhostSlice bundle without modifying it.

The manifest is the authority for order, modes, and metadata. File bodies
come from files/<path> exactly as GhostSlice wrote them; PROMPT.md is the
fallback source, parsed on its '# File: <path> (mode: <label>)' headers.

Manifest paths are validated as relative and contained inside the bundle:
a path that escapes is skipped and recorded, never followed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_HEADER_RE = re.compile(r"^# File: (.+?) \(mode: (.+)\)\s*$", re.MULTILINE)

# The slice modes a GhostSlice manifest can legitimately carry: GhostSlice's
# own MODES tuple (full, signatures, interfaces, structure, strip-tests,
# exclude, headings) plus "symbols", the symbol-level entry mode the bundle
# format documents (see PLAN.md's verification bar). Anything else is carried
# verbatim but flagged as unrecognized; Convert never invents a meaning for
# a label it does not know.
KNOWN_MODES = frozenset({
    "full", "signatures", "interfaces", "structure", "strip-tests",
    "exclude", "headings", "symbols",
})

# sha256 of the empty string. GhostSlice records this hash on entries it
# deliberately emptied (for example a strip-tests result), which is how a
# by-design empty entry is told apart from a body that went missing.
EMPTY_BODY_SHA256 = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")


class BundleError(Exception):
    """The bundle cannot be converted (maps to CLI exit 2)."""


def _contained(base: Path, rel: str) -> Path | None:
    """Resolve base/rel, returning None when it escapes base."""
    if Path(rel).is_absolute():
        return None
    dest = (base / rel).resolve()
    try:
        dest.relative_to(base.resolve())
    except ValueError:
        return None
    return dest


def parse_prompt_bodies(prompt_text: str) -> dict[str, str]:
    """Split PROMPT.md into {path: body} on its file headers.

    GhostSlice joins sections with a '---' rule before each header and
    rstrips each body; bodies here are returned rstripped the same way.
    """
    bodies: dict[str, str] = {}
    matches = list(_HEADER_RE.finditer(prompt_text))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(prompt_text)
        chunk = prompt_text[start:end]
        # Drop the separator rule that precedes the NEXT header.
        chunk = re.sub(r"\n---\s*$", "", chunk.rstrip("\n"))
        bodies[m.group(1)] = chunk.strip("\n")
    return bodies


class BundleFile:
    def __init__(self, entry: dict):
        self.entry = entry
        self.path = entry.get("path", "")
        self.mode = entry.get("mode", "full")
        self.language = entry.get("language", "")
        self.package = entry.get("package")
        self.original_tokens = entry.get("original_tokens")
        self.sliced_tokens = entry.get("sliced_tokens")
        self.sha256 = entry.get("sha256")
        self.body: str | None = None
        self.body_source: str | None = None  # "files" | "prompt" | None

    @property
    def excluded(self) -> bool:
        return self.mode == "exclude"

    @property
    def unknown_mode(self) -> bool:
        """The manifest's mode is not one GhostConvert recognizes."""
        return self.mode not in KNOWN_MODES

    @property
    def emptied_by_design(self) -> bool:
        """No body, and the manifest itself says none was shipped.

        GhostSlice deliberately empties some entries (a strip-tests result
        is the common case): the entry records sliced_tokens 0 and the
        empty-string sha256. That is a slicing decision, not lost content,
        and reports must not conflate the two.
        """
        if self.body is not None or self.excluded:
            return False
        return (self.sliced_tokens == 0
                or (self.sha256 or "").lower() == EMPTY_BODY_SHA256)

    @property
    def missing_body(self) -> bool:
        """No body, though the manifest promises content (nonzero sliced
        tokens or a non-empty hash): the body is genuinely absent."""
        return (self.body is None and not self.excluded
                and not self.emptied_by_design)

    @property
    def mode_label(self) -> str:
        """The label GhostSlice itself prints in PROMPT.md headers."""
        if self.mode == "symbols" and self.entry.get("symbols_included"):
            return "symbols: " + ", ".join(self.entry["symbols_included"])
        return self.mode


class Bundle:
    def __init__(self, root: Path, manifest: dict, files: list[BundleFile],
                 skipped_paths: list[str]):
        self.root = root
        self.manifest = manifest
        self.files = files  # manifest order, excluded included
        self.skipped_paths = skipped_paths

    @property
    def project_name(self) -> str:
        root = self.manifest.get("root") or ""
        return Path(root).name if root else self.root.name

    @property
    def included(self) -> list[BundleFile]:
        return [f for f in self.files if not f.excluded]

    @property
    def excluded(self) -> list[BundleFile]:
        return [f for f in self.files if f.excluded]


def load_bundle(bundle_dir: str | Path) -> Bundle:
    root = Path(bundle_dir).resolve()
    if not root.is_dir():
        raise BundleError(f"bundle directory not found: {bundle_dir}")
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise BundleError(f"no manifest.json in bundle: {root}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError(f"manifest.json is unreadable or malformed: {exc}")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise BundleError("manifest.json has no 'files' list")

    prompt_bodies: dict[str, str] | None = None

    def from_prompt(path: str) -> str | None:
        nonlocal prompt_bodies
        if prompt_bodies is None:
            prompt_path = root / "PROMPT.md"
            try:
                prompt_bodies = parse_prompt_bodies(
                    prompt_path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                prompt_bodies = {}
        body = prompt_bodies.get(path)
        return body if body else None

    files: list[BundleFile] = []
    skipped: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("path"):
            continue
        bf = BundleFile(entry)
        if bf.excluded:
            files.append(bf)
            continue
        dest = _contained(root / "files", bf.path)
        if dest is None:
            skipped.append(bf.path)
            files.append(bf)
            continue
        body = None
        if dest.is_file():
            try:
                body = dest.read_bytes().decode("utf-8", errors="replace")
            except OSError:
                body = None
        if body:
            bf.body = body.rstrip("\n")
            bf.body_source = "files"
        else:
            fallback = from_prompt(bf.path)
            if fallback:
                bf.body = fallback
                bf.body_source = "prompt"
        files.append(bf)
    if not any(f.body for f in files):
        raise BundleError("bundle has no readable file bodies "
                          "(files/ and PROMPT.md both empty or missing)")
    return Bundle(root, manifest, files, skipped)
