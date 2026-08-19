"""
organizer_core.py

Shared logic for the simple file organizer. Used by both organizer.py
(one-off run) and the optional watch.py (continuous watcher).

Behavior:
- Scans the TOP LEVEL of a target folder only (does not recurse into
  subfolders), so files already sorted into category folders are left
  alone on the next run.
- Groups files by extension into subfolders created *inside* the same
  target folder (e.g. ~/Downloads/Images, ~/Downloads/Documents, ...).
- Skips hidden files (dotfiles) by default, and always skips the
  settings.json / log file if they happen to live inside the target
  folder, plus the category folders themselves.
- On a filename collision at the destination, appends " (1)", " (2)",
  etc. rather than overwriting.
- Supports dry-run mode: computes and reports the plan without moving
  anything.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


DEFAULT_OTHERS_FOLDER = "Others"


@dataclass
class Settings:
    target_folder: Path
    dry_run: bool
    skip_hidden_files: bool
    others_folder_name: str
    log_file: Path | None
    categories: dict[str, list[str]]
    ext_to_category: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        ext_map = {}
        for category, extensions in self.categories.items():
            for ext in extensions:
                ext_map[ext.lower().lstrip(".")] = category
        self.ext_to_category = ext_map

    def category_for(self, filename: str) -> str:
        ext = Path(filename).suffix.lower().lstrip(".")
        if not ext:
            return self.others_folder_name
        return self.ext_to_category.get(ext, self.others_folder_name)


def load_settings(config_path: str | Path, overrides: dict | None = None) -> Settings:
    """Load settings.json and apply optional CLI overrides."""
    config_path = Path(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    overrides = overrides or {}
    raw.update({k: v for k, v in overrides.items() if v is not None})

    target_folder = Path(os.path.expanduser(os.path.expandvars(raw["target_folder"])))

    log_file_raw = raw.get("log_file")
    log_file = None
    if log_file_raw:
        log_file = Path(os.path.expanduser(log_file_raw))
        if not log_file.is_absolute():
            # relative log paths live next to the settings file
            log_file = config_path.parent / log_file

    return Settings(
        target_folder=target_folder,
        dry_run=bool(raw.get("dry_run", False)),
        skip_hidden_files=bool(raw.get("skip_hidden_files", True)),
        others_folder_name=raw.get("others_folder_name", DEFAULT_OTHERS_FOLDER),
        log_file=log_file,
        categories=raw.get("categories", {}),
    )


def _unique_destination(dest_dir: Path, filename: str) -> Path:
    """Return a non-colliding path inside dest_dir for filename."""
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        candidate = dest_dir / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _iter_candidate_files(settings: Settings):
    """Yield top-level file paths in the target folder eligible for sorting."""
    category_folder_names = set(settings.categories.keys()) | {settings.others_folder_name}

    with os.scandir(settings.target_folder) as it:
        for entry in it:
            if not entry.is_file(follow_symlinks=False):
                continue
            name = entry.name
            if name in category_folder_names:
                continue
            if settings.skip_hidden_files and name.startswith("."):
                continue
            if settings.log_file and Path(entry.path).resolve() == settings.log_file.resolve():
                continue
            if name == "settings.json":
                continue
            yield Path(entry.path)


def organize(settings: Settings, dry_run_override: bool | None = None) -> dict:
    """
    Run one organizing pass over settings.target_folder.

    Returns a summary dict: {
        "moved": [(src, dest), ...],
        "errors": [(src, error_message), ...],
        "counts": {category: n, ...},
        "dry_run": bool,
    }
    """
    if not settings.target_folder.exists():
        raise FileNotFoundError(f"Target folder does not exist: {settings.target_folder}")
    if not settings.target_folder.is_dir():
        raise NotADirectoryError(f"Target is not a folder: {settings.target_folder}")

    dry_run = settings.dry_run if dry_run_override is None else dry_run_override

    moved: list[tuple[Path, Path]] = []
    errors: list[tuple[Path, str]] = []
    counts: dict[str, int] = {}

    for src in _iter_candidate_files(settings):
        category = settings.category_for(src.name)
        dest_dir = settings.target_folder / category
        dest_path = _unique_destination(dest_dir, src.name)

        try:
            if not dry_run:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest_path))
            moved.append((src, dest_path))
            counts[category] = counts.get(category, 0) + 1
        except OSError as exc:
            errors.append((src, str(exc)))

    result = {"moved": moved, "errors": errors, "counts": counts, "dry_run": dry_run}
    _write_log(settings, result)
    return result


def _write_log(settings: Settings, result: dict) -> None:
    if not settings.log_file:
        return
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    mode = "DRY-RUN" if result["dry_run"] else "MOVED"
    with open(settings.log_file, "a", encoding="utf-8") as f:
        for src, dest in result["moved"]:
            f.write(f"[{timestamp}] {mode}: {src.name} -> {dest.relative_to(settings.target_folder)}\n")
        for src, err in result["errors"]:
            f.write(f"[{timestamp}] ERROR: {src.name}: {err}\n")


def print_summary(result: dict) -> None:
    mode = "DRY RUN (no files were touched)" if result["dry_run"] else "DONE"
    print(f"--- {mode} ---")
    if not result["moved"] and not result["errors"]:
        print("Nothing to organize — target folder is already tidy.")
        return

    verb = "Would move" if result["dry_run"] else "Moved"
    for src, dest in result["moved"]:
        print(f"{verb}: {src.name} -> {dest.parent.name}/{dest.name}")

    for src, err in result["errors"]:
        print(f"ERROR moving {src.name}: {err}")

    if result["counts"]:
        print("\nSummary:")
        for category, n in sorted(result["counts"].items()):
            print(f"  {category}: {n} file(s)")
    if result["errors"]:
        print(f"  Errors: {len(result['errors'])}")
