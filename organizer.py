#!/usr/bin/env python3
"""
organizer.py

One-off run of the simple file organizer: groups files in a target
folder into subfolders by extension (Images/, Documents/, Audio/, ...),
based on settings.json.

Usage:
    python3 organizer.py                     # uses settings.json next to this script
    python3 organizer.py --dry-run           # preview only, touches nothing
    python3 organizer.py --target ~/Desktop  # override target_folder from settings.json
    python3 organizer.py --config /path/to/settings.json

Run this manually whenever you want to tidy up a folder. For automatic /
continuous sorting, see README.md for how to schedule this script.
"""

import argparse
import sys
from pathlib import Path

from organizer_core import load_settings, organize, print_summary


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    default_config = script_dir / "settings.json"

    parser = argparse.ArgumentParser(description="Organize files in a folder by extension.")
    parser.add_argument(
        "--config", default=str(default_config),
        help=f"Path to settings.json (default: {default_config})",
    )
    parser.add_argument(
        "--target", default=None,
        help="Override target_folder from settings.json",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=None,
        help="Preview what would happen without moving any files",
    )
    args = parser.parse_args()

    try:
        settings = load_settings(args.config, overrides={"target_folder": args.target})
    except FileNotFoundError:
        print(f"Config file not found: {args.config}", file=sys.stderr)
        return 1
    except (KeyError, ValueError) as exc:
        print(f"Invalid settings.json: {exc}", file=sys.stderr)
        return 1

    print(f"Organizing: {settings.target_folder}")

    try:
        result = organize(settings, dry_run_override=args.dry_run)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print_summary(result)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
