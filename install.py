#!/usr/bin/env python3
"""Optional explicit local installation; standard library only, no downloads."""
import argparse
import json
import os
from pathlib import Path
import tempfile


def main():
    parser = argparse.ArgumentParser(description="Install the standalone CLI to an explicitly chosen PREFIX/bin.")
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--replace", action="store_true", help="explicitly replace an existing direct-report-audit command")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent / "direct_report_audit.py"
    target = args.prefix.expanduser().resolve() / "bin" / "direct-report-audit"
    if target.exists() or target.is_symlink():
        if not args.replace:
            parser.error("target already exists; choose another prefix or use --replace")
        if target.is_dir():
            parser.error("target is a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".direct-report-audit-", dir=str(target.parent))
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as destination:
            destination.write(source.read_bytes())
        temporary.chmod(0o755)
        if args.replace:
            os.replace(str(temporary), str(target))
        else:
            # Publish a complete file without racing an unrelated installer.
            try:
                os.link(str(temporary), str(target))
            except FileExistsError:
                parser.error("target was created concurrently; installation did not overwrite it")
    finally:
        if temporary.exists():
            temporary.unlink()
    print(json.dumps({"ok": True, "installed": str(target), "network": False, "onboarding_run": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
