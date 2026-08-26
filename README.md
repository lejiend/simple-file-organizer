# Simple File Organizer

Groups files in a folder into subfolders by extension — `Images/`,
`Documents/`, `Spreadsheets/`, `Audio/`, `Video/`, `Archives/`, `Code/`,
`Installers/`, and `Others/` for anything unmatched. By default files are
**copied** into subfolders created inside the same target folder — the
original file is left exactly where it was, untouched. Set
`file_operation` to `"move"` in `settings.json` if you'd rather have the
classic cut-and-paste behavior instead (see [Copy vs. move](#copy-vs-move)
below).

Optionally, before organizing a file, it can ask an AI model to read the
file's content and rename the *copy* (or moved file) to something more
descriptive than `IMG_4821.png` or `download (3).pdf` — see
[AI-powered renaming](#ai-powered-renaming-optional) below.

## 0. Install dependencies

```bash
cd simple-file-organizer
pip3 install -r requirements.txt
```

## 1. Configure

Edit `settings.json`:

- `target_folder` — the folder to organize, e.g. `"~/Downloads"`.
- `dry_run` — `true`/`false` default; can be overridden per run with `--dry-run`.
- `skip_hidden_files` — skip dotfiles (default `true`).
- `others_folder_name` — name of the catch-all folder (default `"Others"`).
- `log_file` — path to a log file (relative paths are relative to this project folder).
- `categories` — extension → folder-name mapping. Add/remove extensions or
  whole categories as you like; anything not listed falls into `Others`.
- `extension_destinations` — optional per-extension override that sends
  matching files to an absolute folder instead of a category subfolder
  (e.g. all `.pdf`s straight into a Google Drive folder).
- `file_operation` — `"copy"` (default: keep the original file in place)
  or `"move"` (classic cut-and-paste, original is gone once sorted). See
  [Copy vs. move](#copy-vs-move) below.
- `ai_rename_enabled`, `ai_model`, `ai_max_content_chars`,
  `ai_timeout_seconds`, `ai_rename_extensions` — see the AI renaming
  section below.

## 2. Run it once

```bash
cd simple-file-organizer
python3 organizer.py --dry-run   # preview, touches nothing
python3 organizer.py             # actually organizes the files
```

Useful flags:

- `--dry-run` — preview only.
- `--target ~/Desktop` — sort a different folder without editing settings.json.
- `--config /path/to/settings.json` — use a different config file.

Run it manually any time you want to tidy up. The script only looks at
the **top level** of the target folder, so files already sorted into a
category subfolder are left alone on the next run.

## Copy vs. move

Controlled by `file_operation` in `settings.json`:

- `"copy"` (default) — the original file is left exactly where it was in
  the target folder, and a copy is placed in the right category
  subfolder. This means the top level of your target folder keeps
  accumulating originals over time — it isn't "tidied" the way move mode
  tidies it — but you always have the untouched original to fall back on.
  To avoid re-copying the same unchanged file on every run (or every
  watcher event), a small manifest file, `.organizer_manifest.json`, is
  kept in the target folder recording what's already been copied and its
  size/modified-time. If a file's content changes later, it's treated as
  new and copied again (as a `(1)`, `(2)`, ... duplicate, never
  overwriting a previous copy).
- `"move"` — classic cut-and-paste: the original is gone once it's
  organized, and the target folder's top level actually stays clean. No
  manifest is needed in this mode, since a moved file simply isn't there
  to be seen again.

Console output, the log file, and `watch.py` all say "Copied"/"Moved" (or
"Would copy"/"Would move" in `--dry-run`) so it's always clear which mode
ran.

## AI-powered renaming (optional)

When enabled, before a file is copied or moved the organizer reads a bit
of its content — plain text, PDF/DOCX text, or the image itself for
pictures — and asks an LLM (via [OpenRouter](https://openrouter.ai)) to
suggest a short, descriptive filename. The suggested name is sanitized
and used in place of the original name, with the original extension
kept. Sorting still happens by extension exactly as before; AI renaming
only changes the *filename*, never the category — and in `"copy"` mode
(the default) it only ever renames the copy, never the original file.

This is entirely best-effort: if it's disabled, the API key is missing,
there's no network, the file type isn't one it knows how to read, or the
API call fails for any reason, the original filename is kept and the
file is still organized normally. Nothing about the AI step can block a
sort or corrupt a file.

### Setup

1. Get an API key from [openrouter.ai](https://openrouter.ai/keys).
2. Put it in a `.env` file in this project folder (already done if you
   see one here):

   ```
   OPEN_ROUTER_API_KEY=sk-or-...
   ```

   `.env` is git-ignored — never commit it.
3. In `settings.json`:

   - `ai_rename_enabled` — `true` to turn the feature on (default `true`).
   - `ai_model` — the OpenRouter model ID to use (default
     `"openai/gpt-4o-mini"`, which is cheap and supports both text and
     images). See [openrouter.ai/models](https://openrouter.ai/models)
     for other options — pick a vision-capable model if you want AI
     renaming to keep covering images.
   - `ai_max_content_chars` — how much of a text/PDF/DOCX file to send
     to the model (default `4000`). Larger values cost a bit more per
     call but give the model more context.
   - `ai_timeout_seconds` — how long to wait for a response before
     giving up and keeping the original name (default `20`).
   - `ai_rename_extensions` — optional allowlist, e.g. `["pdf", "docx"]`,
     to restrict AI renaming to specific file types. Leave as `null` to
     allow every supported type.

### What it can currently read

| Type | Extensions |
|---|---|
| Text | `txt md csv tsv json yml yaml log rtf py js ts jsx tsx html css java c cpp sh rb go php swift` |
| PDF | `pdf` (needs `pypdf`, in requirements.txt) |
| Word | `docx` (needs `python-docx`, in requirements.txt) |
| Images | `png jpg jpeg webp gif bmp` (sent to a vision-capable model) |

Anything else (audio, video, archives, installers, spreadsheets like
`.xlsx`, etc.) is organized by extension as usual, just without renaming
— extraction just isn't implemented for those yet.

### Cost and privacy note

Each eligible file triggers one API call to whatever model you configure
— check OpenRouter's pricing for that model. File content (or, for
images, the image itself) is sent to that model's provider to generate
the suggested name. If that's not something you want for a given target
folder, set `ai_rename_enabled` to `false`, or narrow `ai_rename_extensions`.

## 3. Optional: keep it running automatically

The project intentionally does **not** register anything automatically —
you register whichever option below yourself, on your own schedule.

### Option A — periodic re-run (simplest, no extra dependencies)

Runs `organizer.py` every N minutes via macOS `launchd`. Good enough for
"sort my Downloads every 10 minutes."

1. Create `~/Library/LaunchAgents/com.lejiend.simplefileorganizer.plist`:

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
     "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
     <key>Label</key>
     <string>com.lejiend.simplefileorganizer</string>
     <key>ProgramArguments</key>
     <array>
       <string>/usr/bin/python3</string>
       <string>/Users/lejiend/Documents/Projects/Belajar_Santai/simple-file-organizer/organizer.py</string>
     </array>
     <key>StartInterval</key>
     <integer>600</integer> <!-- seconds, 600 = every 10 minutes -->
     <key>StandardOutPath</key>
     <string>/Users/lejiend/Documents/Projects/Belajar_Santai/simple-file-organizer/launchd.out.log</string>
     <key>StandardErrorPath</key>
     <string>/Users/lejiend/Documents/Projects/Belajar_Santai/simple-file-organizer/launchd.err.log</string>
   </dict>
   </plist>
   ```

2. Load it:

   ```bash
   launchctl load ~/Library/LaunchAgents/com.lejiend.simplefileorganizer.plist
   ```

3. To stop it later:

   ```bash
   launchctl unload ~/Library/LaunchAgents/com.lejiend.simplefileorganizer.plist
   ```

### Option B — real-time watcher (instant sorting, needs `watchdog`)

Sorts a file within a couple seconds of it landing in the folder, instead
of waiting for the next interval.

1. Install the dependency once (already covered by `requirements.txt`,
   or on its own):

   ```bash
   pip3 install --user watchdog
   ```

2. Test it in the foreground first:

   ```bash
   python3 watch.py
   ```

   Leave it running, drop a file into the target folder, confirm it gets
   sorted, then `Ctrl+C` to stop.

3. To keep it running in the background permanently, create
   `~/Library/LaunchAgents/com.lejiend.simplefileorganizerwatch.plist`:

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
     "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
     <key>Label</key>
     <string>com.lejiend.simplefileorganizerwatch</string>
     <key>ProgramArguments</key>
     <array>
       <string>/usr/bin/python3</string>
       <string>/Users/lejiend/Documents/Projects/Belajar_Santai/simple-file-organizer/watch.py</string>
     </array>
     <key>RunAtLoad</key>
     <true/>
     <key>KeepAlive</key>
     <true/>
     <key>StandardOutPath</key>
     <string>/Users/lejiend/Documents/Projects/Belajar_Santai/simple-file-organizer/watch.out.log</string>
     <key>StandardErrorPath</key>
     <string>/Users/lejiend/Documents/Projects/Belajar_Santai/simple-file-organizer/watch.err.log</string>
   </dict>
   </plist>
   ```

4. Load it:

   ```bash
   launchctl load ~/Library/LaunchAgents/com.lejiend.simplefileorganizerwatch.plist
   ```

5. To stop it later:

   ```bash
   launchctl unload ~/Library/LaunchAgents/com.lejiend.simplefileorganizerwatch.plist
   ```

Only run **one** of Option A or Option B at a time for a given folder —
running both would just sort the same folder twice.

## File collisions

If a file with the same name already exists in the destination subfolder,
`(1)`, `(2)`, etc. is appended to the incoming file — nothing is ever
silently overwritten. This applies to AI-renamed files and to repeat
copies of a changed file too.

## Files in this project

- `settings.json` — your configuration.
- `.env` — your `OPEN_ROUTER_API_KEY` (git-ignored, never commit this).
- `requirements.txt` — Python dependencies.
- `organizer_core.py` — shared logic (used by both scripts below).
- `ai_namer.py` — optional AI renaming: content extraction + OpenRouter call.
- `organizer.py` — run this manually (or via Option A) for a one-off sort.
- `watch.py` — optional continuous watcher (used by Option B).
- `.organizer_manifest.json` — auto-created inside your **target folder**
  (not this project folder) when `file_operation` is `"copy"`; tracks
  what's already been copied. Safe to delete if you want a clean slate
  (everything will just get re-copied as a fresh `(1)` on the next run).
- `README.md` — this file.
