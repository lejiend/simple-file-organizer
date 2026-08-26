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
  settings.json / log file / manifest file if they happen to live inside
  the target folder, plus the category folders themselves and Microsoft
  Office lock/temp files (e.g. "~$Agreement.docx").
- Optionally asks an LLM (via OpenRouter) to read each file's content
  and suggest a more descriptive filename before it's organized. See
  ai_namer.py and the ai_* settings below. This is best-effort: if it's
  disabled, unconfigured, or fails for any reason, the original filename
  is kept and the file is still organized normally.
- `file_operation` controls whether files are COPIED (default — the
  original stays where it is, untouched) or MOVED (cut-and-paste, the
  original is gone once sorted) into the category subfolder. In "copy"
  mode a small manifest file (.organizer_manifest.json) is kept in the
  target folder so an unchanged file that's already been copied isn't
  copied again on every subsequent run.
- On a filename collision at the destination, appends " (1)", " (2)",
  etc. rather than overwriting.
- Supports dry-run mode: computes and reports the plan without touching
  anything.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a listed dependency, but don't hard-crash
    load_dotenv = None

import ai_namer

logger = logging.getLogger("organizer")

DEFAULT_OTHERS_FOLDER = "Others"
DEFAULT_AI_MODEL = "openai/gpt-4o-mini"
DEFAULT_AI_MAX_CONTENT_CHARS = 4000
DEFAULT_AI_TIMEOUT_SECONDS = 20
DEFAULT_FILE_OPERATION = "copy"
MANIFEST_FILENAME = ".organizer_manifest.json"


@dataclass
class Settings:
    target_folder: Path
    dry_run: bool
    skip_hidden_files: bool
    others_folder_name: str
    log_file: Path | None
    categories: dict[str, list[str]]
    file_operation: str = DEFAULT_FILE_OPERATION  # "copy" (preserve original) or "move"
    ai_rename_enabled: bool = False
    ai_model: str = DEFAULT_AI_MODEL
    ai_max_content_chars: int = DEFAULT_AI_MAX_CONTENT_CHARS
    ai_timeout_seconds: float = DEFAULT_AI_TIMEOUT_SECONDS
    ai_rename_extensions: set[str] | None = None
    api_key: str | None = field(default=None, repr=False)
    ext_to_category: dict[str, str] = field(default_factory=dict, repr=False)
    extension_destinations: dict[str, Path] = field(default_factory=dict, repr=False)

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

    def ai_eligible(self, filename: str) -> bool:
        """Whether AI renaming should even be attempted for this file."""
        if not self.ai_rename_enabled:
            return False
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext not in ai_namer.SUPPORTED_EXTENSIONS:
            return False
        if self.ai_rename_extensions is not None and ext not in self.ai_rename_extensions:
            return False
        return True

    @property
    def manifest_path(self) -> Path:
        return self.target_folder / MANIFEST_FILENAME


def load_settings(config_path: str | Path, overrides: dict | None = None) -> Settings:
    """Load settings.json and apply optional CLI overrides."""
    config_path = Path(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    overrides = overrides or {}
    raw.update({k: v for k, v in overrides.items() if v is not None})

    # Load .env next to settings.json (project root) so OPEN_ROUTER_API_KEY
    # is picked up without the user having to export it manually.
    if load_dotenv is not None:
        load_dotenv(config_path.parent / ".env")

    target_folder = Path(os.path.expanduser(os.path.expandvars(raw["target_folder"])))

    log_file_raw = raw.get("log_file")
    log_file = None
    if log_file_raw:
        log_file = Path(os.path.expanduser(log_file_raw))
        if not log_file.is_absolute():
            # relative log paths live next to the settings file
            log_file = config_path.parent / log_file

    extension_destinations_raw = raw.get("extension_destinations", {}) or {}
    extension_destinations = {}
    for ext, target in extension_destinations_raw.items():
        if target is None:
            continue
        dest_path = Path(os.path.expanduser(os.path.expandvars(str(target))))
        if not dest_path.is_absolute():
            dest_path = config_path.parent / dest_path
        extension_destinations[ext.lower().lstrip(".")] = dest_path

    ai_rename_extensions_raw = raw.get("ai_rename_extensions")
    ai_rename_extensions = None
    if ai_rename_extensions_raw:
        ai_rename_extensions = {e.lower().lstrip(".") for e in ai_rename_extensions_raw}

    file_operation = str(raw.get("file_operation", DEFAULT_FILE_OPERATION)).lower()
    if file_operation not in ("copy", "move"):
        logger.warning(
            "Invalid file_operation %r in settings — must be 'copy' or 'move'. Falling back to %r.",
            file_operation, DEFAULT_FILE_OPERATION,
        )
        file_operation = DEFAULT_FILE_OPERATION

    api_key = os.environ.get("OPEN_ROUTER_API_KEY")

    settings = Settings(
        target_folder=target_folder,
        dry_run=bool(raw.get("dry_run", False)),
        skip_hidden_files=bool(raw.get("skip_hidden_files", True)),
        others_folder_name=raw.get("others_folder_name", DEFAULT_OTHERS_FOLDER),
        log_file=log_file,
        categories=raw.get("categories", {}),
        file_operation=file_operation,
        ai_rename_enabled=bool(raw.get("ai_rename_enabled", False)),
        ai_model=raw.get("ai_model", DEFAULT_AI_MODEL),
        ai_max_content_chars=int(raw.get("ai_max_content_chars", DEFAULT_AI_MAX_CONTENT_CHARS)),
        ai_timeout_seconds=float(raw.get("ai_timeout_seconds", DEFAULT_AI_TIMEOUT_SECONDS)),
        ai_rename_extensions=ai_rename_extensions,
        api_key=api_key,
        extension_destinations=extension_destinations,
    )

    if settings.ai_rename_enabled and not api_key:
        logger.warning(
            "ai_rename_enabled is true but OPEN_ROUTER_API_KEY is not set "
            "(checked environment and %s) — AI renaming will be skipped "
            "and original filenames will be kept.",
            config_path.parent / ".env",
        )

    return settings


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
            # Microsoft Office lock/temp files (e.g. "~$Agreement.docx"),
            # created while the real file is open elsewhere. Not a real
            # document — always skip regardless of skip_hidden_files.
            if name.startswith("~$"):
                continue
            if settings.log_file and Path(entry.path).resolve() == settings.log_file.resolve():
                continue
            if name in (MANIFEST_FILENAME, "settings.json"):
                continue
            yield Path(entry.path)


def _relative_or_absolute(dest: Path, target_folder: Path) -> str:
    """
    Format a destination path for display/logging: relative to
    target_folder when it lives inside it (the common case), or the full
    absolute path when extension_destinations sent it somewhere else
    entirely (e.g. a Google Drive folder outside target_folder).
    """
    try:
        return str(dest.relative_to(target_folder))
    except ValueError:
        return str(dest)


def _resolve_filename(settings: Settings, src: Path) -> tuple[str, bool]:
    """
    Work out the filename `src` should be organized as: either its
    original name, or an AI-suggested one (with the original extension
    preserved).

    Returns (filename, was_renamed).
    """
    if not settings.ai_eligible(src.name):
        return src.name, False

    try:
        suggested = ai_namer.suggest_filename(src, settings, settings.api_key)
    except Exception as exc:  # noqa: BLE001 - never let AI renaming break a sort
        logger.warning("AI rename raised an unexpected error for %s: %s", src.name, exc)
        suggested = None

    if not suggested:
        return src.name, False

    new_name = f"{suggested}{src.suffix.lower()}"
    return new_name, True


def _load_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read manifest %s (starting fresh): %s", manifest_path, exc)
        return {}


def _save_manifest(manifest_path: Path, manifest: dict) -> None:
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
    except OSError as exc:
        logger.warning("Could not write manifest %s: %s", manifest_path, exc)


def _fingerprint(src: Path) -> dict:
    stat = src.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def organize(settings: Settings, dry_run_override: bool | None = None) -> dict:
    """
    Run one organizing pass over settings.target_folder.

    Returns a summary dict: {
        "moved": [(src, dest, was_renamed), ...],
        "skipped": [(src, reason), ...],
        "errors": [(src, error_message), ...],
        "counts": {category: n, ...},
        "dry_run": bool,
        "operation": "copy" | "move",
    }

    "moved" is named for backwards compatibility with existing callers;
    when file_operation is "copy" these are copies (the source is left
    in place), not moves.
    """
    if not settings.target_folder.exists():
        raise FileNotFoundError(f"Target folder does not exist: {settings.target_folder}")
    if not settings.target_folder.is_dir():
        raise NotADirectoryError(f"Target is not a folder: {settings.target_folder}")

    dry_run = settings.dry_run if dry_run_override is None else dry_run_override
    is_copy = settings.file_operation == "copy"

    manifest: dict = {}
    if is_copy:
        manifest = _load_manifest(settings.manifest_path)

    moved: list[tuple[Path, Path, bool]] = []
    skipped: list[tuple[Path, str]] = []
    errors: list[tuple[Path, str]] = []
    counts: dict[str, int] = {}
    manifest_changed = False

    for src in _iter_candidate_files(settings):
        # Copy mode: the original stays put, so on every later run the
        # same file would otherwise be seen again and copied again. Skip
        # anything already recorded in the manifest with an unchanged
        # size/mtime fingerprint.
        if is_copy:
            try:
                fingerprint = _fingerprint(src)
            except OSError as exc:
                errors.append((src, str(exc)))
                continue
            previous = manifest.get(src.name)
            if previous and previous.get("size") == fingerprint["size"] and previous.get("mtime_ns") == fingerprint["mtime_ns"]:
                skipped.append((src, "already organized (unchanged since last run)"))
                continue

        category = settings.category_for(src.name)
        extension = src.suffix.lower().lstrip(".")
        dest_dir = settings.extension_destinations.get(extension, settings.target_folder / category)

        filename, was_renamed = _resolve_filename(settings, src)
        dest_path = _unique_destination(dest_dir, filename)

        try:
            if not dry_run:
                dest_dir.mkdir(parents=True, exist_ok=True)
                if is_copy:
                    shutil.copy2(str(src), str(dest_path))
                    manifest[src.name] = _fingerprint(src) | {
                        "dest": _relative_or_absolute(dest_path, settings.target_folder),
                    }
                    manifest_changed = True
                else:
                    shutil.move(str(src), str(dest_path))
            moved.append((src, dest_path, was_renamed))
            counts[category] = counts.get(category, 0) + 1
        except OSError as exc:
            errors.append((src, str(exc)))

    if is_copy and manifest_changed and not dry_run:
        _save_manifest(settings.manifest_path, manifest)

    result = {
        "moved": moved,
        "skipped": skipped,
        "errors": errors,
        "counts": counts,
        "dry_run": dry_run,
        "operation": settings.file_operation,
        "target_folder": settings.target_folder,
    }
    _write_log(settings, result)
    return result


def _write_log(settings: Settings, result: dict) -> None:
    if not settings.log_file:
        return
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    verb = "DRY-RUN" if result["dry_run"] else ("COPIED" if result["operation"] == "copy" else "MOVED")
    with open(settings.log_file, "a", encoding="utf-8") as f:
        for src, dest, was_renamed in result["moved"]:
            tag = " (AI-renamed)" if was_renamed else ""
            dest_display = _relative_or_absolute(dest, settings.target_folder)
            f.write(f"[{timestamp}] {verb}{tag}: {src.name} -> {dest_display}\n")
        for src, err in result["errors"]:
            f.write(f"[{timestamp}] ERROR: {src.name}: {err}\n")


def print_summary(result: dict) -> None:
    mode = "DRY RUN (no files were touched)" if result["dry_run"] else "DONE"
    print(f"--- {mode} ---")
    if not result["moved"] and not result["errors"] and not result["skipped"]:
        print("Nothing to organize — target folder is already tidy.")
        return

    if result["dry_run"]:
        verb = "Would copy" if result["operation"] == "copy" else "Would move"
    else:
        verb = "Copied" if result["operation"] == "copy" else "Moved"

    target_folder = result.get("target_folder")
    for src, dest, was_renamed in result["moved"]:
        tag = "  [renamed by AI]" if was_renamed else ""
        dest_display = _relative_or_absolute(dest, target_folder) if target_folder else f"{dest.parent.name}/{dest.name}"
        print(f"{verb}: {src.name} -> {dest_display}{tag}")

    for src, err in result["errors"]:
        print(f"ERROR organizing {src.name}: {err}")

    if result["counts"]:
        print("\nSummary:")
        for category, n in sorted(result["counts"].items()):
            print(f"  {category}: {n} file(s)")
    if result["skipped"]:
        print(f"  Already organized (skipped): {len(result['skipped'])} file(s)")
    if result["errors"]:
        print(f"  Errors: {len(result['errors'])}")
