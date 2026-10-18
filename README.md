# YouTube Instagram Handle Updater

## Redesigned dashboard: quick start

The dashboard uses Link Sans and a red-accented shadcn/ui design with a framed
creator-studio workspace on desktop and a bottom tab bar on mobile. The provided
logo's scalable rendition remains in the header. Use **Ctrl+K** to find a page
and the appearance menu in the header to change themes.

Start with `python web.py`, then open <http://127.0.0.1:8765/#edit>.
If an older copy is running, stop it with **Ctrl+C**, start it again, and press
**Ctrl+F5** in the browser to load the new design and backend together.

1. **Scan for editing** connects your account and reads your descriptions.
   Complete Google sign-in in your browser if prompted.
2. In **Bulk Edit**, choose **All videos** or **Selected videos**. Use the Videos
   page to select individual uploads.
3. Choose **Find & replace** for plain text, or **Update Instagram** for four
   simple username and profile-link fields. Existing saved rules remain intact
   until you save or preview your new settings.
4. **Preview changes** shows highlighted before/after text, full descriptions,
   videos without matches, skipped replacements, and the available update budget.
5. Review the result, then **Apply changes** and type **UPDATE**. Changing a field,
   selection, or saved rules requires another preview. Apply uses the reviewed
   descriptions and selected videos, with a verified backup before writing.

The **How to use** page includes setup, sign-in, backups, downloads, and
troubleshooting. **Sync metadata** gathers statistics and cached descriptions;
it does not replace the scan required for editing. Preview is read-only for
YouTube, but saves your replacement settings locally. Backup restore remains manual.

The following historical sections describe the original CLI job; `main.py`
still uses its original hard-coded Instagram handle, independently of the dashboard.

Developer checks (no live account, downloads, or existing backups are touched):

```powershell
python -B -m unittest test_preview_safety
python -B bulkedit.py --self-test
python -B test_ui_redesign.py
```

The browser check requires Python Playwright, an installed Chrome browser, and
`npm.cmd ci` for the local axe accessibility-checking dependency.
It mocks every request and writes desktop/mobile screenshots to `.ui-preview/`.

### Frontend development

The compiled frontend is included, so **Node is not needed to run the app**.
To change and rebuild the interface, install Node.js 22.12 or newer, then run:

```powershell
npm.cmd ci
npm.cmd run check
npm.cmd run build
```

`frontend/template.html` contains page content. `frontend/build.tsx` renders
shadcn controls into `ui.html`, preserving the IDs used by `app.js`.
`frontend/main.tsx` owns navigation, dialogs, sheets, command search, and toasts;
`frontend/styles.css` defines base controls and `frontend/device.css` defines
the responsive layout. Link Sans loads locally from `assets/fonts/`. Source-owned shadcn
components live in `frontend/components/ui`. Vite bundles the runtime into
`assets/ui/`. Rebuild after editing frontend sources; do not hand-edit generated
`ui.html` or `assets/ui/`.

Video filters live under **Filter & sort**. Download settings use a dialog with
**Output**, **Extras**, **Filters**, and **System** tabs. Exports and private-video
cookie settings are on **Tools**. These dialogs retain form values when closed;
they do not add new persistence beyond the existing application behavior.

See `UX_REDESIGN.md` for the page audit and presentation-layer architecture.

---

Safely replaces an old Instagram handle inside **YouTube video descriptions**, leaving
every other character of each description untouched.

```
@crm.drm                 ->  @prod.crmdrm
instagram.com/crm.drm    ->  instagram.com/prod.crmdrm
```

Nothing else changes. Your titles, BeatStars links, e-mail addresses, licensing text,
credits, `Prod. CRMDRM` branding, tags, category, privacy, thumbnails and monetization
settings are all left exactly as they are.

**The default mode is a read-only preview.** The script cannot modify anything until
you answer `yes` and then type `UPDATE` in capital letters.

---

## What is in here

| File | What it does |
| --- | --- |
| `web.py` | **Channel Toolkit** — the local web dashboard. Start here. |
| `main.py` | The original Instagram-handle job (command line). |
| `bulkedit.py` | Generalised, safe find-and-replace rule engine. |
| `ytdlp.py` | Free channel reads through yt-dlp — stats, export, thumbnails. |
| `fix_oversize.py` | Fits descriptions that pass the 5000-character limit. |
| `ui.html`, `app.js` | The dashboard front end. |
| `rules.json` | Your bulk-edit rules. Created on first run. |

Every one of them shares the same `update_progress.json` checkpoint, the same
backup format and the same safety rules, so you can mix the dashboard and the
command line freely.

---

## The two data sources, and why it matters

The YouTube Data API gives you **10,000 quota units a day**, and a single
description write costs **50** of them. Reading through **yt-dlp** costs nothing
at all. So the toolkit splits the work:

| | yt-dlp | YouTube Data API |
| --- | --- | --- |
| Cost | free, unlimited | 10,000 units/day |
| Speed | ~1 second per video | instant, but rationed |
| Sees private videos | only with browser cookies | yes |
| Can write | **no** | yes — the only way |
| Gives view/like counts | **yes** | costs extra quota |

Reads are pushed onto yt-dlp so the whole daily quota stays available for the
one thing that actually needs it: changing descriptions.

---

## The dashboard

```bash
python web.py
```

Your browser opens at <http://127.0.0.1:8765>. It listens on `127.0.0.1` only,
so nothing on your network can reach it. Press **Ctrl+C** in PowerShell to stop.

> If it says something is already listening on that port, an older copy is still
> running. Close its window first — it refuses to start rather than silently
> shadowing the old one and showing you a stale page.

**Two buttons in the top bar:**

- **Sync (free)** — reads every public and unlisted video through yt-dlp:
  descriptions, view counts, like counts, durations, upload dates. About
  8 minutes for 450 videos. Costs **zero** quota.
- **API scan** — reads through the YouTube API. Slower to sign in, costs about
  21 units, but it sees **private** videos and is the only source you can write
  from. Required before any bulk edit.

**Five sections:**

1. **Overview** — totals, view counts, like rate, watch time, top and least
   viewed uploads, live quota meter with a countdown to the reset in your own
   time zone, and a live activity log.
2. **Videos** — every video in a sortable, searchable table with thumbnails,
   views, likes, like rate, description length and privacy. Filter by privacy,
   by short descriptions, or by descriptions near the 5000-character limit.
   Tick rows to scope a bulk edit to just those.
3. **Bulk Edit** — see below.
4. **Links** — every URL across your descriptions, grouped by domain with a
   count of how many videos mention it. Useful for spotting a link that appears
   on 400 videos before it breaks.
5. **Tools** — CSV/JSON export, thumbnail download, browser-cookie setting for
   private videos, and a pointer to the oversize fixer.

Light and dark themes, keyboard accessible, and usable down to a 375px phone
screen. Colours were checked against WCAG AA: the lowest contrast ratio on the
page is 6.29:1 in light mode and 5.95:1 in dark, against a 4.5:1 requirement.

---

## Bulk Edit

The Instagram job was one hard-coded find-and-replace. Bulk Edit generalises it
to any rule you write, keeping every safety property that made the original
survivable.

A rule has a **find**, a **replace with**, and — the important part — a list of
**protected strings**:

| Field | Meaning |
| --- | --- |
| Type | `Plain text` or `Regex` |
| Find / Replace with | what to look for, and what to put there |
| **Protect** | strings that must appear the **same number of times** before and after |
| Case sensitive | off by default |
| Whole word only | plain-text rules only |

If a rule would change a protected string, that rule is **skipped for that
video** and reported — the other rules still apply. It is how you stop a
careless rule from eating `business.crmdrm@gmail.com`.

**Four more guards run automatically on every rule, on every video:**

1. A rule that would push a description past 5000 characters is rejected.
2. A rule that would rewrite more than 35% of a description is rejected as
   almost certainly a mistake.
3. A rule that would **delete a link** it was not explicitly targeting is
   rejected.
4. Invalid regexes, back-references to groups that do not exist, and patterns
   that match the empty string are caught when you save, not when you write.

The flow is always: **Dry run → read the BEFORE/AFTER diffs → Apply → type
`UPDATE`**. A verified backup is written before the first change and progress
is checkpointed after every video, exactly as in the original job.

Run the engine's own tests any time, with no credentials and no internet:

```bash
python bulkedit.py --self-test
```

---

## Download & Archive

The **Download** page pulls media off YouTube with yt-dlp. It is separate from
everything else in this toolkit: it only writes files to your disk, and never
touches your descriptions or spends API quota.

> Use it for content you own or have permission to download. yt-dlp does not
> bypass DRM, and neither does this.

**Presets** set everything in one click:

| Preset | What it fetches |
| --- | --- |
| **Full channel backup** | Video + thumbnail + description + info JSON + captions, with an archive file so nothing is fetched twice |
| **Video, 1080p MP4** | Merged MP4 with tags and cover art |
| **Audio only, MP3** | Best-quality MP3 with cover art and metadata — good for your beats |
| **Audio only, WAV** | Uncompressed, for re-editing in a DAW |
| **Metadata only** | Info JSON + description + thumbnail, no media, very fast |
| **Captions only** | Subtitles and auto-captions as SRT |
| **Thumbnails only** | Every thumbnail as a JPG |
| **New uploads, last 7 days** | Point at a channel and run it on a schedule |

**Everything is adjustable:** resolution up to 4K, container (MP4/MKV/WebM),
audio format (MP3/M4A/FLAC/WAV/Opus/AAC/ALAC), subtitle languages and format,
embedded thumbnails/metadata/chapters, SponsorBlock (mark as chapters or cut
out), file-naming templates, browser cookies for private videos, download-rate
limits, and filters by duration, view count, upload date, playlist range or
time section.

**Three buttons before you commit:**

- **List formats** — the raw `yt-dlp -F` table for a URL, so you can see exactly
  what resolutions exist.
- **Preview command** — builds and validates the command and shows it in full.
  You can paste it straight into PowerShell if you would rather run it yourself.
- **Start download** — runs it, with live progress in the Activity log.

### How the options are kept safe

Every value you type is checked against an allow-list before it becomes a flag,
and the command is handed to the OS as an argument list, never through a shell.
A free-text field cannot turn into an extra option: `--exec calc.exe` typed into
the filter box is rejected as an unreadable filter clause, `../../Windows` in the
folder box is rejected, and `file:///C:/...` is rejected as not an http(s) URL.

```bash
python download.py --self-test
```
runs 47 checks covering every mode, every preset and every injection attempt.
No network, nothing downloaded.

### Command line

```bash
python download.py --env
```
Show yt-dlp, FFmpeg and JS-runtime versions.

```bash
python download.py --formats "https://www.youtube.com/watch?v=..."
```
List available formats.

```bash
python download.py --preset channel-backup --url "CHANNEL_URL" --dry-run
```
Print the command without running it. Drop `--dry-run` to actually fetch.

### What it needs

| Tool | Why | Status on this machine |
| --- | --- | --- |
| **yt-dlp** | everything | present, but see below |
| **FFmpeg** | merging video+audio, converting audio, converting thumbnails | installed |
| **Node or Deno** | YouTube now needs a JS runtime; without one some higher formats are hidden | Node found and used automatically |

**Keeping yt-dlp current matters.** YouTube changes its stream signing often,
and an out-of-date build gets `HTTP 403: Forbidden` on media downloads while
metadata, captions and thumbnails keep working. The Download page detects this
and shows a warning. To update:

```bash
.\yt-dlp.exe -U
```

### What yt-dlp cannot do

It is a downloader and metadata extractor. It cannot upload, edit descriptions,
change titles or thumbnails, schedule uploads, delete videos, manage comments,
or bypass DRM. Editing your descriptions is what the rest of this toolkit does,
through the YouTube Data API.

---

## yt-dlp from the command line

Everything the dashboard does with yt-dlp is also available directly:

```bash
python ytdlp.py --sync
```
Read every video's full metadata into `ytdlp_cache.json`. Free.

```bash
python ytdlp.py --stats
```
Total views, likes, median, like rate, total runtime, top 5.

```bash
python ytdlp.py --export
```
Write `channel_export.csv` (opens in Excel) and `channel_export.json`.

```bash
python ytdlp.py --thumbnails
```
Download every thumbnail as a JPG into `thumbnails/`.

```bash
python ytdlp.py --sync --cookies-from-browser chrome
```
Include private videos by borrowing your browser's cookies. Close the browser
first or it may refuse to read the cookie file.

---

## The original command-line job

`main.py` still works exactly as it always did, and shares the same checkpoint
file as the dashboard:

| Command | What it does |
| --- | --- |
| `python main.py --self-test` | 24 replacement tests. No credentials, no internet. |
| `python main.py --preview-only` | Read-only preview. Cannot modify anything. |
| `python main.py --preview-only --show-all` | Preview every affected video. |
| `python main.py --limit 10 --preview-only` | Preview the 10 most recent uploads. |
| `python main.py` | Preview, then offer update mode (`yes`, then `UPDATE`). |
| `python main.py --max-updates 5` | Update at most 5 videos this run. |
| `python main.py --reset-progress` | Forget the checkpoint. Does not undo anything on YouTube. |

---

## Table of contents

**Using it:** [What is in here](#what-is-in-here) ·
[The two data sources](#the-two-data-sources-and-why-it-matters) ·
[The dashboard](#the-dashboard) · [Bulk Edit](#bulk-edit) ·
[yt-dlp CLI](#yt-dlp-from-the-command-line) ·
[Original CLI job](#the-original-command-line-job)

**First-time setup (Google Cloud):**

1. [Install Python on Windows](#step-1--install-python-on-windows)
2. [Check Python in PowerShell](#step-2--check-python-in-powershell)
3. [Create a Google Cloud project](#step-3--create-a-google-cloud-project)
4. [Enable the YouTube Data API v3](#step-4--enable-the-youtube-data-api-v3)
5. [Configure the OAuth consent screen](#step-5--configure-the-oauth-consent-screen)
6. [Create an OAuth 2.0 Desktop App credential](#step-6--create-an-oauth-20-desktop-app-credential)
7. [Download the OAuth JSON](#step-7--download-the-oauth-json)
8. [Place and rename the credential file](#step-8--place-and-rename-the-credential-file)
9. [Install the Python dependencies](#step-9--install-the-python-dependencies)
10. [Run preview mode](#step-10--run-preview-mode)
11. [Review the proposed changes](#step-11--review-the-proposed-changes)
12. [Run update mode](#step-12--run-update-mode)
13. [Authenticate with the correct channel](#step-13--authenticate-with-the-correct-youtube-account--channel)
14. [Verify a few videos manually](#step-14--verify-a-few-videos-manually)
15. [Resume if the script stops](#step-15--resume-if-the-script-stops)

**Reference:** [API quota maths](#api-quota-maths) ·
[Over-length descriptions](#videos-that-are-too-long-the-5000-character-limit) ·
[What gets matched](#what-gets-matched) · [Files created](#files-this-project-creates) ·
[Restoring from backup](#restoring-from-a-backup) · [Troubleshooting](#troubleshooting)

---

## Step 1 — Install Python on Windows

If you already have Python 3.9 or newer, skip to Step 2.

1. Go to <https://www.python.org/downloads/windows/>
2. Download the latest **Windows installer (64-bit)**.
3. Run the installer.
4. **On the very first screen, tick the box "Add python.exe to PATH".** This matters —
   without it PowerShell will not find Python.
5. Click **Install Now** and wait for it to finish.
6. Close and reopen PowerShell so it picks up the new PATH.

---

## Step 2 — Check Python in PowerShell

Open PowerShell (press the Windows key, type `powershell`, press Enter) and run:

```bash
python --version
```

You should see something like `Python 3.10.11`. Also check pip:

```bash
pip --version
```

If `python` is not recognised, reinstall Python and make sure "Add python.exe to PATH"
is ticked, then reopen PowerShell.

Now move into the project folder:

```bash
cd "E:\Desktop\Code Projects\youtube-description-fix"
```

Confirm you are in the right place:

```bash
Get-ChildItem
```

You should see `main.py`, `requirements.txt`, `.gitignore` and `README.md`.

---

## Step 3 — Create a Google Cloud project

The YouTube Data API is free, but it needs a Google Cloud project to issue you
credentials. There is no cost and no credit card required.

1. Go to <https://console.cloud.google.com/>
2. Sign in with **the Google account that owns your YouTube channel**.
3. At the top of the page, click the **project dropdown** (to the right of the "Google
   Cloud" logo).
4. Click **New project**.
5. Name it something like `youtube-description-fix`.
6. Leave *Location / Organization* as-is.
7. Click **Create**, wait a few seconds, then use the project dropdown again to
   **select the new project**. Everything below must happen inside this project.

---

## Step 4 — Enable the YouTube Data API v3

1. Go to <https://console.cloud.google.com/apis/library/youtube.googleapis.com>
2. Make sure your new project is selected in the top dropdown.
3. Click the blue **Enable** button.
4. Wait for the page to reload and show the API dashboard.

---

## Step 5 — Configure the OAuth consent screen

Google requires this before it will issue you a credential.

1. Go to <https://console.cloud.google.com/auth/overview> (older layout:
   *APIs & Services → OAuth consent screen*).
2. If prompted, click **Get started**.
3. **App name**: anything, e.g. `Description Updater`.
4. **User support email**: pick your own e-mail from the dropdown.
5. **Audience / User type**: choose **External**.
   (*Internal* only exists for Google Workspace organisations. External is correct for
   a normal personal Google account.)
6. **Contact information**: enter your own e-mail again.
7. Agree to the user data policy and click **Create**.

Then add yourself as a test user:

8. Go to **Audience** in the left-hand menu.
9. Under **Test users**, click **+ Add users**.
10. Type the e-mail address of the Google account that owns your YouTube channel and
    click **Save**.

> **Why this matters:** while the app is in *Testing* status, only listed test users can
> sign in. If you skip this you will get `Error 403: access_denied` at sign-in time.
>
> You do **not** need to publish the app or go through Google's verification review. A
> testing-mode refresh token expires after 7 days, which is completely fine here — this
> job takes about 3 days and the script will simply ask you to sign in again if needed.

---

## Step 6 — Create an OAuth 2.0 Desktop App credential

1. Go to <https://console.cloud.google.com/apis/credentials>
2. Click **+ Create credentials** at the top → **OAuth client ID**.
3. **Application type**: select **Desktop app**.
   This is important — Desktop app is what lets the script open a browser and receive
   the response on `localhost`.
4. **Name**: `Desktop client` (or anything you like).
5. Click **Create**.

---

## Step 7 — Download the OAuth JSON

1. A dialog appears saying *OAuth client created*.
2. Click **Download JSON** (if you close the dialog, find your client in the
   *OAuth 2.0 Client IDs* list and click the download icon on its row).
3. The file lands in your Downloads folder with a long name like
   `client_secret_1234567890-abcdefg.apps.googleusercontent.com.json`.

**Treat this file like a password.** Do not e-mail it, post it, or commit it to git.
The included `.gitignore` already excludes it.

---

## Step 8 — Place and rename the credential file

The file must be named exactly `client_secret.json` and sit next to `main.py`.

Copy and rename it in one PowerShell command (adjust the source path if your Downloads
folder differs):

```bash
Copy-Item "$env:USERPROFILE\Downloads\client_secret_*.json" "E:\Desktop\Code Projects\youtube-description-fix\client_secret.json"
```

Verify it is there:

```bash
Get-ChildItem "E:\Desktop\Code Projects\youtube-description-fix\client_secret.json"
```

Sanity-check that it is a **Desktop app** credential (this prints only the structure,
never your secret):

```bash
python -c "import json; d=json.load(open('client_secret.json')); print(list(d.keys()))"
```

It must print `['installed']`. If it prints `['web']` you created the wrong credential
type — go back to Step 6 and choose **Desktop app**.

---

## Step 9 — Install the Python dependencies

From the project folder:

```bash
pip install -r requirements.txt
```

That installs:

| Package | Why |
| --- | --- |
| `google-api-python-client` | Talks to the YouTube Data API v3 |
| `google-auth-oauthlib` | Handles the OAuth 2.0 browser sign-in |
| `google-auth-httplib2` | HTTP transport for the auth layer |
| `tzdata` | Windows has no built-in timezone database; needed to track the quota day in Pacific Time |

If `pip` is not recognised, use:

```bash
python -m pip install -r requirements.txt
```

Now run the built-in replacement tests. **This needs no credentials and no internet**,
and proves the matching rules do the right thing before you go anywhere near your
channel:

```bash
python main.py --self-test
```

You should see `SELF-TEST PASSED: all 24 cases correct.`

---

## Step 10 — Run preview mode

Preview is the default. There is no flag to remember and no way to skip straight to
updating.

**Start with a small test on your 10 most recent uploads:**

```bash
python main.py --limit 10 --preview-only
```

Then, once that looks right, preview the whole channel:

```bash
python main.py --preview-only
```

The first time you run it, a browser window opens. See
[Step 13](#step-13--authenticate-with-the-correct-youtube-account--channel) for exactly
what to click.

`--preview-only` guarantees the script exits without even offering to update. Use it
freely — it is completely read-only.

To print every single proposed change instead of just the first 25:

```bash
python main.py --preview-only --show-all
```

To save the whole preview to a text file you can read at your leisure:

```bash
python main.py --preview-only --show-all | Tee-Object -FilePath preview.txt
```

---

## Step 11 — Review the proposed changes

The preview prints, for each affected video:

```
------------------------------------------------------------------------------
[1] [FREE] Drake Type Beat - "Nightfall" | Prod. CRMDRM
    https://www.youtube.com/watch?v=abc123  (public)
    rule   : Instagram @handle
    BEFORE : ...to purchase this beat and avoid fees. Instagram: @crm.drm Email: business.crmdrm@gmail.com...
    AFTER  : ...to purchase this beat and avoid fees. Instagram: @prod.crmdrm Email: business.crmdrm@gmail.com...
```

and finishes with the summary:

```
Total videos scanned: 446
Videos containing old Instagram: 312
Videos that would be changed: 312
Videos with no change needed: 134
```

**What to check before approving:**

- The channel name at the top is genuinely yours.
- In every `AFTER` line, `business.crmdrm@gmail.com`, `Prod. CRMDRM`, BeatStars links
  and `crmdrm.beats` are **unchanged**. Only `@crm.drm` and `instagram.com/crm.drm`
  should differ from the `BEFORE` line.
- Look at the `FYI` section at the bottom. Those videos say `crm.drm` with no `@` and
  no `instagram.com` in front of it, so the script deliberately leaves them alone as
  too ambiguous to touch automatically. Edit those by hand in YouTube Studio if you
  want them changed.
- If any video is listed under "would exceed 5000 characters", it is skipped
  automatically — the new handle is 4 characters longer than the old one and that
  description is already at YouTube's limit. Shorten it by hand first.

---

## Step 12 — Run update mode

When you are happy with the preview, run without `--preview-only`:

```bash
python main.py
```

It shows the same preview again, then asks you three separate times:

1. `Do you want to proceed to UPDATE mode? (yes/no):` — type `yes`
2. A warning: `You are about to modify 312 YouTube video descriptions.` followed by
   `Type exactly  UPDATE  to proceed (anything else cancels):` — type `UPDATE`
   (capital letters, nothing else — even `update` cancels)
3. The backup is written and **verified by reading it back** before a single API write
   happens. If the backup fails for any reason, the run is cancelled and nothing is
   changed.

Then it works through the videos:

```
[1/446] Updated: [FREE] Drake Type Beat - "Nightfall" | Prod. CRMDRM
[2/446] Skipped: old Instagram not found
[3/446] Updated: [FREE] Travis Scott Type Beat - "Ember"
```

**Recommended first real run — change just 5 videos, then go look at them:**

```bash
python main.py --max-updates 5
```

Check those 5 in YouTube Studio ([Step 14](#step-14--verify-a-few-videos-manually)),
and if they are perfect, run `python main.py` again to continue with the rest. The
checkpoint file means those first 5 are never touched twice.

You can press **Ctrl+C at any time**. Progress is saved after every single video.

---

## Step 13 — Authenticate with the correct YouTube account / channel

On the first run a browser tab opens:

1. **Choose an account** — pick the Google account that owns the YouTube channel.
   If you have several Google accounts, this is the most common place to go wrong.
2. You will see **"Google hasn't verified this app"**. This is expected — it is *your
   own* app, in testing mode. Click **Advanced**, then
   **Go to *Description Updater* (unsafe)**.
   (If instead you get `Error 403: access_denied`, you skipped adding yourself as a
   test user — go back to Step 5.)
3. A permission screen asks for access to *"See, edit, and permanently delete your
   YouTube videos, ratings, comments and captions"*. That broad wording is Google's
   standard label for the `youtube.force-ssl` scope; this script only ever calls
   `videos.update` with the `snippet` part. Click **Continue** / **Allow**.
4. The browser shows *"The authentication flow has completed."* — close the tab and
   return to PowerShell.

A `token.json` file is created so you do not have to sign in every time.

**Immediately check the channel name the script prints:**

```
  Channel: CRMDRM  (UCxxxxxxxxxxxxxxxxxxxxxx)
```

If that is the wrong channel, stop and switch accounts:

```bash
Remove-Item token.json
python main.py --preview-only
```

> **Brand accounts:** if your channel is a Brand Account, the account picker shows the
> channel as a separate entry. Choose the channel entry, not your personal Gmail
> identity.

---

## Step 14 — Verify a few videos manually

After a run, pick a handful of the updated videos and check them in the real world.

Open a video straight from the backup file:

```bash
python -c "import json;d=json.load(open('youtube_descriptions_backup.json',encoding='utf-8'));[print('https://www.youtube.com/watch?v='+v['video_id'],'|',v['title']) for v in d['videos'][:5]]"
```

For each one:

1. Open it in **YouTube Studio → Content → click the video → Details**.
2. Confirm the Instagram handle now reads `@prod.crmdrm`.
3. Confirm the **title** is unchanged.
4. Scroll the whole description — confirm your e-mail, BeatStars links, licensing text
   and credits are all still exactly as before.
5. Check the **tags** field is still populated.
6. Check **Visibility** (public / unlisted / private) is unchanged.
7. Check the **thumbnail** is unchanged.

YouTube's front-end sometimes caches the old description for a few minutes; YouTube
Studio always shows the truth.

You can also diff any video against the backup:

```bash
python -c "import json;d=json.load(open('youtube_descriptions_backup.json',encoding='utf-8'));v=d['videos'][0];import difflib;print('\n'.join(difflib.unified_diff(v['original_description'].splitlines(),v['new_description'].splitlines(),'BEFORE','AFTER',lineterm='')))"
```

---

## Step 15 — Resume if the script stops

If the script stops for **any** reason — quota exhausted, internet dropped, computer
restarted, token expired, unexpected error, or you pressed Ctrl+C — just run it again:

```bash
python main.py
```

Every successful update is recorded in `update_progress.json` the instant it succeeds.
On the next run those videos are reported as
`Skipped: already updated in a previous run` and cost you zero quota.

Because 446 videos need more quota than one day allows, this is the normal path, not an
error path. Expect roughly **three sessions on three different days**.

Check what is left at any time:

```bash
python -c "import json;p=json.load(open('update_progress.json',encoding='utf-8'));print('completed:',len(p['completed']));print('failed:',len(p['failed']));print('quota by day:',p['quota_by_pt_date'])"
```

See which videos failed and why:

```bash
python -c "import json;p=json.load(open('update_progress.json',encoding='utf-8'));[print(k,'->',v['error'][:160]) for k,v in p['failed'].items()]"
```

Failed videos are **not** marked complete, so a later run retries them automatically.

To start completely over (this does *not* undo anything on YouTube — it only forgets
what was already done, and would cause videos to be updated a second time):

```bash
python main.py --reset-progress
```

---

## API quota maths

Verified against the official documentation on 2026-08-24:

- <https://developers.google.com/youtube/v3/determine_quota_cost>
- <https://developers.google.com/youtube/v3/getting-started>

| API method | Used for | Cost |
| --- | --- | --- |
| `channels.list` | find your channel + uploads playlist | **1 unit** |
| `playlistItems.list` | list video IDs, 50 per page | **1 unit** per page |
| `videos.list` | read descriptions, 50 per call | **1 unit** per call |
| `videos.update` | write one new description | **50 units** |

Default project allocation: **10,000 units per day**, resetting at **midnight Pacific
Time**.

For 446 videos:

```
Scanning everything (a full preview):
   1  x channels.list        =    1 unit
   9  x playlistItems.list   =    9 units   (ceil(446 / 50))
   9  x videos.list          =    9 units   (ceil(446 / 50))
                             -------------
                                 19 units   <- a full preview is basically free

Updating everything:
 446  x videos.update x 50   = 22,300 units
```

**22,300 units is more than the 10,000/day allowance**, so the job cannot finish in one
day. The script handles this for you:

- It keeps a running total of units spent per Pacific-Time day in
  `update_progress.json` and stops before hitting the ceiling (it reserves 150 units of
  headroom).
- Roughly **197 videos can be updated per day**, so about **3 days** in total.
- If YouTube returns `quotaExceeded` anyway, the script catches it, saves progress and
  exits cleanly instead of crashing.
- Re-running after the reset picks up exactly where it left off.

You do not need to request a quota increase. Just run the script again the next day.

---

## What gets matched

**Changed:**

| Input | Output |
| --- | --- |
| `@crm.drm` | `@prod.crmdrm` |
| `@CRM.DRM` | `@prod.crmdrm` |
| `instagram.com/crm.drm` | `instagram.com/prod.crmdrm` |
| `https://www.instagram.com/crm.drm` | `https://www.instagram.com/prod.crmdrm` |
| `http://instagram.com/crm.drm/` | `http://instagram.com/prod.crmdrm/` |
| `https://m.instagram.com/crm.drm?igshid=x` | `https://m.instagram.com/prod.crmdrm?igshid=x` |

**Deliberately left alone** (your brand name, not your handle):

`Prod. CRMDRM` · `Produced by CRMDRM` · `business.crmdrm@gmail.com` · `crmdrm.beats` ·
`beatstars.com/crmdrm` · `youtube.com/@crmdrm` · `@crm.drmx` · `notinstagram.com/crm.drm` ·
`someone@crm.drm` (an e-mail address, not a handle)

**Reported but not changed:** a bare `crm.drm` with no `@` and no `instagram.com` in
front of it. Too ambiguous to touch automatically — the preview lists these under `FYI`
so you can handle them by hand.

Every one of these cases is a test in `python main.py --self-test`, and the test suite
runs automatically at the start of every real run. If it ever fails, the script
refuses to continue.

---

## Files this project creates

| File | What it is | Safe to delete? |
| --- | --- | --- |
| `client_secret.json` | Your Google OAuth credential. **You provide this.** | No |
| `token.json` | Your saved sign-in. Created on first run. | Yes — you'll sign in again |
| `youtube_descriptions_backup.json` | Original + new descriptions, written before any change | Keep until you're certain |
| `oversize_backup.json` | Same, for videos fixed by `fix_oversize.py` | Keep until you're certain |
| `backups/backup-<timestamp>.json` | A timestamped copy of every backup, never overwritten | Keep at least one |
| `update_progress.json` | Checkpoint: which videos are done, plus quota spent per day | No — deleting it loses resume |
| `rules.json` | Your bulk-edit rules | Only if you want to start over |
| `ytdlp_cache.json` | Free metadata cache: descriptions, views, likes | Yes — re-sync takes ~8 min |
| `channel_export.csv` / `.json` | Exports you asked for | Yes |
| `thumbnails/` | Downloaded thumbnails | Yes |
| `preview.txt`, `oversize_videos.txt` | Reports you generated | Yes |

Every one of these is in `.gitignore`, so none can be committed by accident.

> **Note on `preview.txt`:** PowerShell's `Tee-Object` writes UTF-16, so tools like
> `grep` and `findstr` will appear to find nothing in it. Open it in Notepad or
> VS Code instead, or read it with
> `Get-Content preview.txt`.

--- | --- | --- |
| `client_secret.json` | Your Google OAuth credential. **You provide this.** | No — you'd have to re-download it |
| `token.json` | Your saved sign-in. Created on first run. | Yes — you'll just sign in again |
| `youtube_descriptions_backup.json` | Every original + new description, written before any change | Keep it until you're certain |
| `backups/backup-<timestamp>.json` | A timestamped copy of each backup, never overwritten | Keep at least one |
| `update_progress.json` | Checkpoint: which video IDs are done, plus quota spent per day | No — deleting it loses resume |

All of these are in `.gitignore`, so none of them can be committed by accident.

---

## Restoring from a backup

Every original description is stored verbatim in `youtube_descriptions_backup.json`.
To read the original text of a specific video:

```bash
python -c "import json,sys;d=json.load(open('youtube_descriptions_backup.json',encoding='utf-8'));v=[x for x in d['videos'] if x['video_id']=='PUT_VIDEO_ID_HERE'][0];print(v['original_description'])"
```

Copy the output and paste it back into YouTube Studio. For a bulk restore, tell me and
I'll add a `--restore` mode — I left it out on purpose so there is no code path in this
script that can mass-overwrite descriptions with old data by accident.

---

## Troubleshooting

**`python: The term 'python' is not recognized`**
Python is not on PATH. Reinstall it with "Add python.exe to PATH" ticked, then reopen
PowerShell.

**`ERROR: client_secret.json not found`**
The file is missing or misnamed. Re-do Step 8. Note that Windows may hide the `.json`
extension — check with `Get-ChildItem` rather than trusting the File Explorer name.

**`Error 403: access_denied` during sign-in**
You are not listed as a test user on the OAuth consent screen. Go back to Step 5 and
add your own e-mail under **Audience → Test users**.

**`Google hasn't verified this app`**
Expected. Click **Advanced → Go to ... (unsafe)**. It is your own app.

**`accessNotConfigured` / `YouTube Data API v3 has not been used in project ...`**
The API is not enabled, or you enabled it in a different Cloud project than the one
your credential belongs to. Re-do Step 4 with the correct project selected.

**`quotaExceeded`**
Expected partway through. Progress is saved. Run again after midnight Pacific Time.

**`invalid_grant` / `Token has been expired or revoked`**
Testing-mode refresh tokens expire after 7 days. Fix:
```bash
Remove-Item token.json
python main.py
```

**The script found fewer videos than I expected**
It reads your channel's *uploads* playlist, which includes public, unlisted and private
uploads. It does not include videos on a different channel under the same Google
account — check the channel name and ID it printed.

**A video shows the old handle even after a successful update**
Two possibilities: (a) YouTube's public page is cached — check YouTube Studio instead;
or (b) the video has a *translated* description, which lives in a separate
`localizations` field that this script does not touch by design. The preview flags
those with `NOTE: this video has a translated description`.

**Wrong channel**
```bash
Remove-Item token.json
python main.py --preview-only
```
and pick the right account.

---

## Videos that are too long (the 5000-character limit)

`prod.crmdrm` is 4 characters longer than `crm.drm`, so a description already at
YouTube's 5000-character ceiling no longer fits after the swap. `main.py` skips those
rather than truncating anything, and lists them under
`SKIPPED - the new description would exceed YouTube's 5000-character limit`.

`fix_oversize.py` fits them using **whitespace-only** edits, applied least-visible
first and stopping the moment the description fits:

1. trailing spaces/tabs at the end of each line *(invisible)*
2. blank space at the very end of the description *(invisible)*
3. runs of 4+ blank lines collapsed to 3 *(barely visible)*
4. runs of 3+ blank lines collapsed to 2 *(slightly visible)*
5. runs of 2+ blank lines collapsed to 1 *(visible)*

No word, link, tag, e-mail or punctuation mark is ever removed. The script verifies
this itself: it strips all whitespace from the before and after text and refuses to
write unless they are identical. Anything that still does not fit is left completely
alone and listed for manual editing.

Preview first (read-only, ~21 quota units):

```bash
python fix_oversize.py
```

It prints, per video, how many characters each step saved, whether the edits were
invisible, and the end of the description before and after with trailing spaces shown
as `·`. Then apply:

```bash
python fix_oversize.py --apply
```

You must type `UPDATE` in capitals. A separate verified backup is written to
`oversize_backup.json` first, because `main.py`'s backup does not cover these videos.
Successful fixes are recorded in the same `update_progress.json`, so nothing is done
twice.

Run the whitespace tests any time, with no credentials and no internet:

```bash
python fix_oversize.py --self-test
```

### How characters are counted

YouTube's limit is 5000. An emoji is 1 Python code point but 2 UTF-16 code units, and
these descriptions contain plenty of emoji, so the script measures conservatively as
`max(code points, UTF-16 units)`. Evidence from this channel: the longest description
YouTube accepted was 4998 code points / 5000 UTF-16 units, and nothing longer by
either measure was accepted.

---

## Command reference

```bash
python main.py --self-test
```
Run the 24 replacement tests. No credentials, no internet, no API calls.

```bash
python main.py --preview-only
```
Read-only preview of the whole channel. Cannot modify anything.

```bash
python main.py --preview-only --show-all
```
Preview showing every affected video instead of the first 25.

```bash
python main.py --limit 10 --preview-only
```
Preview only the 10 most recent uploads.

```bash
python main.py
```
Preview, then offer update mode (requires `yes`, then `UPDATE`).

```bash
python main.py --max-updates 5
```
Update at most 5 videos this run. Best way to do your first real run.

```bash
python main.py --reset-progress
```
Forget the checkpoint and start over. Does not undo anything on YouTube.
