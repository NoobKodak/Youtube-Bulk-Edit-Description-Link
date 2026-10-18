# Channel Toolkit desktop

The Windows installer is built in `release/Channel-Toolkit-Setup-1.0.1.exe`.
The installed application bundles Electron, Python, Google API libraries,
yt-dlp, FFmpeg/FFprobe and Node for yt-dlp's JavaScript runtime.
Python and Node do not need to be installed on the target computer.

Start **Channel Toolkit** from the Start menu or desktop shortcut.
The branded loading screen waits for the private backend's actual readiness.
Each launch binds a free localhost port and uses a new private session token.
Only this application's backend and its children are stopped on exit.
Closing during an active job asks whether to keep working.

## Data and migration

Settings, OAuth credentials, metadata, quota checkpoints, backups and logs
live under `%APPDATA%\Channel Toolkit`. The installer contains no user data.
Migration copies known data files and missing backup/thumbnail files only;
existing destinations are preserved. Original project files are retained.
Existing downloads stay in the original project download folder. New
workspaces default to the user's Downloads/Channel Toolkit folder.
The download destination can be changed on the download page.
Uninstalling preserves application data.

On a new computer, first launch asks for the previous project folder.
Cancel starts a new workspace. Supply your own Google desktop OAuth
`client_secret.json` in the data folder before scanning. Sign-in opens the
system browser and returns through Google's loopback OAuth flow.

## Rebuilding

Development needs Node, Python, the requirements in `requirements.txt`,
PyInstaller, local `yt-dlp.exe`, FFmpeg/FFprobe on PATH, and Chrome for the
logo render. Run `npm ci`, then `npm run desktop:build`.
The build script uses an explicit asset allowlist and never copies project
credentials, rules, cache, backups or downloads into the installer.

Tests:

```
python -B -m unittest test_preview_safety.py test_desktop_auth.py
node --test desktop/storage.test.cjs
python -B test_ui_redesign.py
node scripts/test_desktop.cjs "release/win-unpacked/Channel Toolkit.exe"
```

Tests use mocked updates, authentication and downloads. The desktop smoke
test opens an empty local test folder; it does not download any media.
No live YouTube writes are part of these checks.

## Troubleshooting and limitations

Check `desktop.log` and `backend.log` in the data folder for startup errors.
Your browser server on port 8765 can run independently. Avoid operating both
workspaces on the same channel at once: their quota checkpoints are separate.
The installer is unsigned because no code-signing certificate was supplied.
Windows may display its normal publisher/reputation prompt; security checks
are not disabled. Live Google consent and real media downloads require your
account/network and are intentionally not exercised during testing.

Runtime license notices are installed in `resources/licenses`. The local
FFmpeg build is GPLv3; the notice records its build/source location. This
installer was prepared for personal local use. Distribution requires review
of corresponding-source obligations for FFmpeg and other bundled components.
