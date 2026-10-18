# GhostConvert

GhostConvert takes a finished [GhostSlice](https://github.com/littlestjames82-sys/ghostslice)
bundle and re-expresses it in the instruction formats other coding
agents actually read: an `AGENTS.md`, Cursor rules, GitHub Copilot
instructions, or one plain prompt file.

GhostSlice decides what an agent reads. GhostConvert only changes the
shape that reading arrives in. It makes no slicing decisions of its
own, never re-slices, and never edits the bundle. Anything a target
format cannot carry from the Slice manifest is named in a `LOSSES.md`
file shipped with the output, instead of being dropped silently.

Zero dependencies, Python standard library only, runs fully locally.

## Install

```sh
pip install .
```

That puts a `ghostconvert` command on your PATH. From a source
checkout without installing:

```sh
PYTHONPATH=src python3 -m ghostconvert --help
```

Requires Python 3.10 or newer.

## Quick start

```sh
# See what a bundle holds, writing nothing
ghostconvert inspect path/to/.claude_context

# Convert it for tools that read AGENTS.md
ghostconvert convert path/to/.claude_context --to agents -o out/agents

# Convert it to every target at once (one subdirectory per target)
ghostconvert convert path/to/.claude_context --to all -o out/all
```

## The four targets

| Target | Artifact written | Notes |
|---|---|---|
| `agents` | `AGENTS.md` | One document, one section per file, body in a fenced block |
| `cursor` | `.cursor/rules/*.mdc` | One rule file per top-level directory, with frontmatter (description, globs, alwaysApply) |
| `copilot` | `.github/copilot-instructions.md` | Same section discipline as `agents` |
| `generic` | `prompt.md` | Plain concatenation with `# File:` headers, closest to Slice's own `PROMPT.md` |

`ghostconvert targets` lists the same table from the CLI.

Every conversion also writes `LOSSES.md` into the output directory
(one per target subdirectory when converting `--to all`).

## How conversion works

- The bundle's `manifest.json` is the authority for file order, slice
  modes, language, token estimates, and hashes. Converted artifacts
  keep the manifest's file order exactly.
- File bodies come from the bundle's `files/` directory, byte for
  byte as Slice wrote them. If a `files/` entry is missing, the body
  is recovered from the bundle's `PROMPT.md` instead. If neither has
  it, the file is converted as absent and named in `LOSSES.md`.
- Each file's section header carries its slice mode, for example
  `## File: src/util.py (mode: signatures)`. A file marked signatures,
  symbols, interfaces, or strip-tests is not the full source, and the
  header is the warning.
- Manifest paths that would escape the bundle directory are skipped
  and named in `LOSSES.md`. They are never followed.

## The losses note

Formats like `AGENTS.md` are single prose documents. They have nowhere
to put per-file sha256 hashes, per-file token counts, redaction
records, symbol lists, or the list of files Slice excluded. Hand
conversion drops all of that without a word. GhostConvert writes it
down instead: each `LOSSES.md` names, as applicable, the excluded
files, the hashes and token estimates that did not carry, redaction
metadata, mode reasons, package groupings, files whose bodies were not
found, skipped paths, and format-specific losses (for Cursor, the
regrouping into rule files is itself named as a loss). Two distinctions
are kept exact in the note: a file Slice emptied on purpose (an empty
slice in the manifest) is listed separately from a file whose body is
genuinely missing, and a slice mode GhostConvert does not recognize is
flagged as unrecognized while its label is still carried verbatim. A
conversion that lost nothing says so in the note rather than omitting
the file.

## Safety rules

- The source bundle is read only. Conversion hashes nothing into it
  and writes nothing into it; the test suite verifies byte for byte
  that a bundle is unchanged after every conversion.
- Output goes to a directory you name with `-o`. It must not be the
  bundle directory or inside it; the run refuses and exits 2.
- Existing files at the exact artifact paths are overwritten only
  with `--force`. Without it the run refuses, names the collision,
  and writes nothing.
- A malformed manifest, or a bundle with no readable file bodies at
  all, exits 2 (could not convert) rather than producing a partial
  silent success.
- Exit codes: 0 means converted (losses, if any, are listed in
  `LOSSES.md` and are not failures). 2 means a bad bundle or bad
  arguments.

## Honest limits

- Converted context is still sliced context. GhostConvert re-expresses
  what Slice decided; it cannot restore code Slice cut. Verify the
  source bundle (for example with `ghostslice check`) when you need
  guarantees, because converted output carries no hashes to check
  against.
- Cursor grouping by top-level directory is a judgement call,
  recorded as a loss. The receiving tool sees rule files Slice never
  made.
- Target format shapes are pinned as written by this version (Cursor
  `.mdc` frontmatter and the Copilot instructions path as of October
  2026). If those tools change their conventions, that is a
  GhostConvert version bump, not a silent edit.
- No reverse conversion. There is no path from a converted artifact
  back to a bundle, and no round-trip guarantee.
- Out of scope for v0.1: re-slicing or rescanning the project, merging
  output into a live project's existing instruction files (that step
  is yours), targets beyond the four above, and any network, account,
  or telemetry features. There are none.

## Development

```sh
PYTHONPATH=src python3 -m pytest tests -q
```

The test suite is black-box: it drives the CLI as a subprocess
(discovered via `$GHOSTCONVERT_CMD`, PATH, or `python -m ghostconvert`
with `PYTHONPATH=src`) and builds its golden bundle with the real
GhostSlice. See `REPORT_B.md` for the latest run and findings, and
`PLAN.md` for the design.
