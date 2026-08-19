#!/usr/bin/env python3
"""
watch.py (optional)

Continuous watcher: keeps running and sorts new files into the
extension-group subfolders as soon as they show up in target_folder.

This script is NOT registered to run automatically by anything in this
project — see README.md for the manual steps to register it (or the
simpler periodic-run alternative) with macOS launchd.

Requires the 'watchdog' package:
    pip3 install --user watchdog

Usage:
    python3 watch.py                    # uses settings.json next to this script
    python3 watch.py --config /path/to/settings.json
"""

import argparse
import sys
import time
from pathlib import Path

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print(
        "The 'watchdog' package is required for continuous watching.\n"
        "Install it with:  pip3 install --user watchdog",
        file=sys.stderr,
    )
    raise SystemExit(1)

from organizer_core import load_settings, organize


# Small delay after a file appears before we try to move it, so large
# files that are still being written/downloaded aren't grabbed mid-copy.
SETTLE_SECONDS = 2.0


class SortOnCreate(FileSystemEventHandler):
    def __init__(self, settings):
        self.settings = settings

    def _handle(self, path: str):
        p = Path(path)
        if p.name.startswith(".") and self.settings.skip_hidden_files:
            return
        time.sleep(SETTLE_SECONDS)
        if not p.exists():
            return  # e.g. a temp file that got renamed/removed already
        result = organize(self.settings)
        for src, dest in result["moved"]:
            print(f"Sorted: {src.name} -> {dest.parent.name}/{dest.name}")
        for src, err in result["errors"]:
            print(f"ERROR moving {src.name}: {err}", file=sys.stderr)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(event.dest_path)


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    default_config = script_dir / "settings.json"

    parser = argparse.ArgumentParser(description="Continuously watch and organize a folder.")
    parser.add_argument("--config", default=str(default_config))
    args = parser.parse_args()

    settings = load_settings(args.config)
    print(f"Watching: {settings.target_folder}  (Ctrl+C to stop)")

    # Sort anything that's already sitting there before we start watching.
    organize(settings)

    handler = SortOnCreate(settings)
    observer = Observer()
    observer.schedule(handler, str(settings.target_folder), recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
