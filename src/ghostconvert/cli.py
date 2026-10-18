"""GhostConvert CLI: convert | inspect | targets.

Exit codes: 0 = done (losses recorded in LOSSES.md are not failures),
2 = bad bundle or bad arguments, source bundle never modified.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from . import __version__
from .bundle import BundleError, load_bundle
from .convert import TARGETS, TARGET_ARTIFACTS, convert


def _cmd_targets(_args) -> int:
    print("GhostConvert targets:")
    for t in TARGETS:
        print(f"  {t:8} -> {TARGET_ARTIFACTS[t]}")
    print("Every target also writes LOSSES.md next to its artifact(s).")
    return 0


def _cmd_inspect(args) -> int:
    try:
        bundle = load_bundle(args.bundle)
    except BundleError as exc:
        print(f"ghostconvert: {exc}", file=sys.stderr)
        return 2
    m = bundle.manifest
    modes = Counter(f.mode for f in bundle.files)
    print(f"Bundle: {bundle.root}")
    print(f"Project: {bundle.project_name}")
    print(f"Sliced by: {m.get('tool', 'unknown')} {m.get('version', '')} "
          f"(preset: {m.get('preset', 'unknown')})")
    with_bodies = sum(1 for f in bundle.included if f.body is not None)
    emptied_n = sum(1 for f in bundle.included if f.emptied_by_design)
    missing_n = sum(1 for f in bundle.included if f.missing_body)
    census = [f"{with_bodies} with bodies"]
    if emptied_n:
        census.append(f"{emptied_n} emptied by GhostSlice")
    if missing_n:
        census.append(f"{missing_n} missing bodies")
    census.append(f"{len(bundle.excluded)} excluded")
    print(f"Files: {len(bundle.files)} ({', '.join(census)})")
    for mode, n in sorted(modes.items()):
        note = ""
        if any(f.unknown_mode for f in bundle.files if f.mode == mode):
            note = " (unrecognized mode, carried verbatim)"
        print(f"  mode {mode}: {n}{note}")
    total_sliced = m.get("total_sliced_tokens")
    total_original = m.get("total_original_tokens")
    if total_sliced is None or total_original is None:
        print("Totals: not recorded in the manifest")
    else:
        print(f"Totals: {total_sliced} sliced of "
              f"{total_original} original estimated tokens "
              f"(method: {m.get('token_method', 'unknown')})")
    unknown_modes = sorted({f.mode for f in bundle.files if f.unknown_mode})
    if unknown_modes:
        print(f"Unrecognized mode(s): {', '.join(unknown_modes)} "
              f"(not a mode GhostConvert knows; labels are carried "
              f"verbatim, never relabelled)")
    emptied = [f for f in bundle.included if f.emptied_by_design]
    if emptied:
        print("Emptied by GhostSlice (no body by design): "
              + ", ".join(f"{f.path} (mode: {f.mode})" for f in emptied))
    missing = [f.path for f in bundle.included if f.missing_body]
    if missing:
        print(f"Missing bodies: {', '.join(missing)}")
    if bundle.skipped_paths:
        print(f"Skipped (paths escape bundle): {', '.join(bundle.skipped_paths)}")
    return 0


def _write_artifacts(outdir: Path, artifacts: dict[str, str],
                     force: bool) -> list[str] | None:
    """Write all artifacts or none. Returns written paths, or None after
    printing the collision that blocked the run."""
    collisions = [str(outdir / rel) for rel in artifacts
                  if (outdir / rel).exists()]
    if collisions and not force:
        print("ghostconvert: refusing to overwrite existing file(s) "
              "(use --force to replace):", file=sys.stderr)
        for c in collisions:
            print(f"  {c}", file=sys.stderr)
        return None
    written = []
    for rel, text in artifacts.items():
        dest = outdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        written.append(rel)
    return written


def _cmd_convert(args) -> int:
    try:
        bundle = load_bundle(args.bundle)
    except BundleError as exc:
        print(f"ghostconvert: {exc}", file=sys.stderr)
        return 2
    out_base = Path(args.out).resolve()
    if out_base == bundle.root or bundle.root in out_base.parents:
        print("ghostconvert: output directory must not be the bundle "
              "directory or inside it; the source bundle is read-only.",
              file=sys.stderr)
        return 2
    targets = list(TARGETS) if args.to == "all" else [args.to]
    for target in targets:
        outdir = out_base / target if args.to == "all" else out_base
        artifacts, losses = convert(bundle, target)
        written = _write_artifacts(outdir, artifacts, args.force)
        if written is None:
            return 2
        bodies = sum(1 for f in bundle.included if f.body is not None)
        print(f"[{target}] {bodies} file(s) converted -> {outdir}")
        for rel in written:
            print(f"  wrote {rel}")
        if losses:
            print(f"  losses: {len(losses)} named in LOSSES.md "
                  f"({', '.join(name for name, _ in losses)})")
        else:
            print("  losses: none recorded")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ghostconvert",
        description="Convert a GhostSlice bundle into other agent "
                    "instruction formats, naming what each format loses.")
    parser.add_argument("--version", action="version",
                        version=f"ghostconvert {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_targets = sub.add_parser("targets", help="list conversion targets")
    p_targets.set_defaults(func=_cmd_targets)

    p_inspect = sub.add_parser("inspect", help="summarise a bundle, write nothing")
    p_inspect.add_argument("bundle", help="path to the GhostSlice bundle directory")
    p_inspect.set_defaults(func=_cmd_inspect)

    p_convert = sub.add_parser("convert", help="convert a bundle to a target format")
    p_convert.add_argument("bundle", help="path to the GhostSlice bundle directory")
    p_convert.add_argument("--to", required=True,
                           choices=[*TARGETS, "all"],
                           help="target format (all = one subdirectory per target)")
    p_convert.add_argument("-o", "--out", required=True,
                           help="output directory (must not be inside the bundle)")
    p_convert.add_argument("--force", action="store_true",
                           help="overwrite artifacts that already exist")
    p_convert.set_defaults(func=_cmd_convert)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
