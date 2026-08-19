# Simple File Organizer

Groups files in a folder into subfolders by extension — `Images/`,
`Documents/`, `Spreadsheets/`, `Audio/`, `Video/`, `Archives/`, `Code/`,
`Installers/`, and `Others/` for anything unmatched. Files are **moved**
into subfolders created inside the same target folder.

## 1. Configure

Edit `settings.json`:

- `target_folder` — the folder to organize, e.g. `"~/Downloads"`.
- `dry_run` — `true`/`false` default; can be overridden per run with `--dry-run`.
- `skip_hidden_files` — skip dotfiles (default `true`).
- `others_folder_name` — name of the catch-all folder (default `"Others"`).
- `log_file` — path to a log file (relative paths are relative to this project folder).
- `categories` — extension → folder-name mapping. Add/remove extensions or
  whole categories as you like; anything not listed falls into `Others`.

## 2. Run it once

```bash
cd simple-file-organizer
python3 organizer.py --dry-run   # preview, touches nothing
python3 organizer.py             # actually sorts the files
```

Useful flags:

- `--dry-run` — preview only.
- `--target ~/Desktop` — sort a different folder without editing settings.json.
- `--config /path/to/settings.json` — use a different config file.

Run it manually any time you want to tidy up. The script only looks at
the **top level** of the target folder, so files already sorted into a
category subfolder are left alone on the next run.

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

1. Install the dependency once:

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
the mover appends `(1)`, `(2)`, etc. to the incoming file — nothing is
ever silently overwritten.

## Files in this project

- `settings.json` — your configuration.
- `organizer_core.py` — shared logic (used by both scripts below).
- `organizer.py` — run this manually (or via Option A) for a one-off sort.
- `watch.py` — optional continuous watcher (used by Option B).
- `README.md` — this file.
