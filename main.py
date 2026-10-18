#!/usr/bin/env python3
"""
YouTube bulk Instagram-handle updater.

Replaces an old Instagram handle / profile URL inside YouTube video
descriptions while leaving every other character of the description
untouched.

    @crm.drm                 ->  @prod.crmdrm
    instagram.com/crm.drm    ->  instagram.com/prod.crmdrm

Default mode is a read-only PREVIEW (dry run). Nothing on YouTube is
modified until you explicitly approve and type UPDATE.

Run `python main.py --help` for options.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Make sure we can print emoji / non-ASCII descriptions on a Windows console.
# --------------------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from zoneinfo import ZoneInfo

    PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - fallback if tzdata is missing
    PACIFIC = timezone(timedelta(hours=-8))


# ==========================================================================
# CONFIGURATION
# ==========================================================================

OLD_HANDLE = "crm.drm"
NEW_HANDLE = "prod.crmdrm"

CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.json"
BACKUP_FILE = "youtube_descriptions_backup.json"
BACKUP_DIR = "backups"
PROGRESS_FILE = "update_progress.json"

# videos.update requires write access to the account's videos.
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# YouTube's hard limit on a video description.
MAX_DESCRIPTION_LENGTH = 5000

# --------------------------------------------------------------------------
# Quota costs, taken from the official documentation (verified 2026-08-24):
#   https://developers.google.com/youtube/v3/determine_quota_cost
#   https://developers.google.com/youtube/v3/getting-started
#
#   channels.list ......  1 unit
#   playlistItems.list .  1 unit
#   videos.list ........  1 unit
#   videos.update ...... 50 units
#
# Default project allocation: 10,000 units per day, resetting at midnight
# Pacific Time.
#
# 446 videos x 50 units = 22,300 units -> roughly 3 days of quota.
# That is why the checkpoint / resume system below is mandatory, not optional.
# --------------------------------------------------------------------------
QUOTA_COST = {
    "channels.list": 1,
    "playlistItems.list": 1,
    "videos.list": 1,
    "videos.update": 50,
}
DAILY_QUOTA_LIMIT = 10_000
# Leave a little headroom so we never trip the limit mid-write.
QUOTA_SAFETY_RESERVE = 150


# ==========================================================================
# REPLACEMENT ENGINE  (pure text, no network - covered by --self-test)
# ==========================================================================

# 1) Instagram profile URLs, with or without scheme / subdomain:
#       https://www.instagram.com/crm.drm
#       http://instagram.com/crm.drm/
#       m.instagram.com/crm.drm?igshid=...
#    The leading \b stops "notinstagram.com/crm.drm" from matching.
URL_RE = re.compile(
    r"(?i)\b((?:https?://)?(?:[a-z0-9-]+\.)*instagram\.com/)crm\.drm(?!\.?\w)"
)

# 2) The bare @handle.
#    Lookbehind: the '@' must not be preceded by e-mail-ish characters, so
#    "someone@crm.drm" (an address) is left alone.
#    Lookahead: not followed by a word char, and not by ".word", so
#    "@crm.drmx" and "@crm.drm.beats" are left alone, while a sentence
#    ending in "@crm.drm." still matches.
HANDLE_RE = re.compile(r"(?i)(?<![\w.+\-])@crm\.drm(?!\.?\w)")

# Detection only - never replaced. A bare "crm.drm" with no '@' and no
# instagram.com in front of it is ambiguous, so we only report it.
BARE_RE = re.compile(r"(?i)(?<![\w.@/+\-])crm\.drm(?!\.?\w)")

RULES = [
    ("Instagram URL", URL_RE, r"\1" + NEW_HANDLE),
    ("Instagram @handle", HANDLE_RE, "@" + NEW_HANDLE),
]


def apply_replacements(text):
    """Return (new_text, hits) where hits is a list of dicts describing each
    replacement. `text` is returned unchanged if there is nothing to do."""
    if not text:
        return text, []

    hits = []
    new_text = text
    for label, pattern, repl in RULES:
        matches = list(pattern.finditer(new_text))
        if not matches:
            continue
        for m in matches:
            hits.append({"rule": label, "matched": m.group(0)})
        new_text = pattern.sub(repl, new_text)

    return new_text, hits


def find_bare_mentions(text):
    """Occurrences of 'crm.drm' that we deliberately do NOT touch."""
    if not text:
        return []
    return [m.group(0) for m in BARE_RE.finditer(text)]


def context_snippets(old_text, new_text, width=70):
    """Build BEFORE/AFTER excerpts around each change, for the preview."""
    snippets = []
    for label, pattern, _repl in RULES:
        for m in pattern.finditer(old_text):
            start = max(0, m.start() - width)
            end = min(len(old_text), m.end() + width)
            before = old_text[start:end]
            after, _ = apply_replacements(before)
            snippets.append(
                {
                    "rule": label,
                    "before": _flatten(before, start > 0, end < len(old_text)),
                    "after": _flatten(after, start > 0, end < len(old_text)),
                }
            )
    return snippets


def _flatten(s, lead_ellipsis, trail_ellipsis):
    s = s.replace("\r", " ").replace("\n", " \\n ")
    s = re.sub(r"\s{2,}", " ", s).strip()
    return ("..." if lead_ellipsis else "") + s + ("..." if trail_ellipsis else "")


# ==========================================================================
# SELF TEST  (no credentials, no network required)
# ==========================================================================

SELF_TEST_CASES = [
    # (input, expected output)
    (
        "Reach out to me via email or Instagram to purchase this beat and "
        "avoid fees. Instagram: @crm.drm Email: business.crmdrm@gmail.com",
        "Reach out to me via email or Instagram to purchase this beat and "
        "avoid fees. Instagram: @prod.crmdrm Email: business.crmdrm@gmail.com",
    ),
    (
        "https://www.instagram.com/crm.drm",
        "https://www.instagram.com/prod.crmdrm",
    ),
    ("instagram.com/crm.drm", "instagram.com/prod.crmdrm"),
    ("http://instagram.com/crm.drm/", "http://instagram.com/prod.crmdrm/"),
    (
        "https://m.instagram.com/crm.drm?igshid=abc123",
        "https://m.instagram.com/prod.crmdrm?igshid=abc123",
    ),
    ("IG:@crm.drm", "IG:@prod.crmdrm"),
    ("(@crm.drm)", "(@prod.crmdrm)"),
    ("Follow me @crm.drm.", "Follow me @prod.crmdrm."),
    ("Follow @CRM.DRM today", "Follow @prod.crmdrm today"),
    ("@crm.drm\nnext line", "@prod.crmdrm\nnext line"),
    (
        "IG: @crm.drm\nIG: https://www.instagram.com/crm.drm\nProd. CRMDRM",
        "IG: @prod.crmdrm\nIG: https://www.instagram.com/prod.crmdrm\nProd. CRMDRM",
    ),
    # --- must NOT change ---
    ("Prod. CRMDRM", "Prod. CRMDRM"),
    ("Produced by CRMDRM", "Produced by CRMDRM"),
    ("business.crmdrm@gmail.com", "business.crmdrm@gmail.com"),
    ("crmdrm.beats", "crmdrm.beats"),
    ("[FREE] Type Beat | Prod. CRMDRM", "[FREE] Type Beat | Prod. CRMDRM"),
    ("https://www.beatstars.com/crmdrm", "https://www.beatstars.com/crmdrm"),
    ("contact@crm.drm.co", "contact@crm.drm.co"),
    ("someone@crm.drm", "someone@crm.drm"),
    ("@crm.drmx", "@crm.drmx"),
    ("notinstagram.com/crm.drm", "notinstagram.com/crm.drm"),
    ("youtube.com/@crmdrm", "youtube.com/@crmdrm"),
    ("@prod.crmdrm", "@prod.crmdrm"),
    ("", ""),
]


def run_self_test(verbose=True):
    if verbose:
        print("Running replacement self-test (no network, no credentials)...\n")
    failures = 0
    for i, (src, expected) in enumerate(SELF_TEST_CASES, 1):
        got, _hits = apply_replacements(src)
        ok = got == expected
        if not ok:
            failures += 1
            print(f"  [{i:2}] FAIL")
            print(f"       input    : {src!r}")
            print(f"       expected : {expected!r}")
            print(f"       got      : {got!r}")
        elif verbose:
            print(f"  [{i:2}] ok   {src!r}")
    if verbose:
        print()
    if failures:
        print(f"SELF-TEST FAILED: {failures} of {len(SELF_TEST_CASES)} cases.")
        return 1
    if verbose:
        print(f"SELF-TEST PASSED: all {len(SELF_TEST_CASES)} cases correct.")
    return 0


# ==========================================================================
# SMALL FILE HELPERS
# ==========================================================================


def atomic_write_json(path, data):
    """Write JSON to a temp file, flush to disk, then rename into place."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        print(f"WARNING: could not read {path}: {exc}")
        return default


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pacific_date():
    return datetime.now(PACIFIC).strftime("%Y-%m-%d")


# ==========================================================================
# PROGRESS / CHECKPOINT
# ==========================================================================


def load_progress():
    data = read_json(
        PROGRESS_FILE,
        {"version": 1, "completed": {}, "failed": {}, "quota_by_pt_date": {}},
    )
    data.setdefault("completed", {})
    data.setdefault("failed", {})
    data.setdefault("quota_by_pt_date", {})
    return data


def save_progress(progress):
    atomic_write_json(PROGRESS_FILE, progress)


# ==========================================================================
# QUOTA TRACKER
# ==========================================================================


class QuotaTracker:
    """Tracks quota spend for the current Pacific-Time day, persisted in the
    progress file so it survives restarts."""

    def __init__(self, progress):
        self.progress = progress
        self.date = pacific_date()
        self.spent = int(progress["quota_by_pt_date"].get(self.date, 0))
        self.spent_this_run = 0

    def remaining(self):
        return max(0, DAILY_QUOTA_LIMIT - QUOTA_SAFETY_RESERVE - self.spent)

    def can_afford(self, method):
        return QUOTA_COST[method] <= self.remaining()

    def spend(self, method):
        cost = QUOTA_COST[method]
        self.spent += cost
        self.spent_this_run += cost
        self.progress["quota_by_pt_date"][self.date] = self.spent

    def summary(self):
        return (
            f"quota used today (PT {self.date}): {self.spent}/{DAILY_QUOTA_LIMIT} "
            f"units | this run: {self.spent_this_run} | "
            f"remaining safe budget: {self.remaining()}"
        )


# ==========================================================================
# YOUTUBE API
# ==========================================================================


class QuotaExceeded(Exception):
    pass


def build_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("ERROR: required Google libraries are not installed.")
        print("Run:  pip install -r requirements.txt")
        sys.exit(1)

    if not os.path.exists(CLIENT_SECRET_FILE):
        print(f"ERROR: {CLIENT_SECRET_FILE} not found in {os.getcwd()}")
        print("See the README for how to download it from Google Cloud Console.")
        sys.exit(1)

    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as exc:
            print(f"Stored token unreadable ({exc}); starting a fresh sign-in.")
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            print(f"Token refresh failed ({exc}); starting a fresh sign-in.")
            creds = None

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
        print("\nA browser window will open so you can sign in to Google.")
        print("IMPORTANT: choose the Google account that owns your YouTube channel.\n")
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        atomic_write_json(TOKEN_FILE, json.loads(creds.to_json()))
        print(f"Sign-in complete. Token saved to {TOKEN_FILE}\n")

    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def http_error_reason(exc):
    try:
        payload = json.loads(exc.content.decode("utf-8"))
        return payload["error"]["errors"][0].get("reason", "")
    except Exception:
        return ""


def execute_with_retry(request, quota, method, max_attempts=4):
    """Execute an API request, retrying transient failures with backoff.
    Quota exhaustion is raised immediately as QuotaExceeded."""
    from googleapiclient.errors import HttpError

    for attempt in range(1, max_attempts + 1):
        quota.spend(method)  # failed calls also cost quota
        try:
            return request.execute()
        except HttpError as exc:
            reason = http_error_reason(exc)
            status = getattr(exc.resp, "status", None)
            if reason in ("quotaExceeded", "dailyLimitExceeded"):
                raise QuotaExceeded(str(exc)) from exc
            transient = reason == "rateLimitExceeded" or (
                status is not None and int(status) >= 500
            )
            if transient and attempt < max_attempts:
                delay = (2 ** attempt) + random.random()
                print(f"    transient error ({reason or status}); retrying in {delay:.1f}s")
                time.sleep(delay)
                continue
            raise


def get_channel(youtube, quota):
    resp = execute_with_retry(
        youtube.channels().list(part="snippet,contentDetails", mine=True),
        quota,
        "channels.list",
    )
    items = resp.get("items", [])
    if not items:
        print("ERROR: no YouTube channel found for this Google account.")
        print("Sign in with the account that owns the channel "
              "(delete token.json to switch accounts).")
        sys.exit(1)
    ch = items[0]
    return {
        "id": ch["id"],
        "title": ch["snippet"]["title"],
        "uploads_playlist": ch["contentDetails"]["relatedPlaylists"]["uploads"],
    }


def list_upload_video_ids(youtube, quota, uploads_playlist, limit=None):
    video_ids = []
    page_token = None
    while True:
        resp = execute_with_retry(
            youtube.playlistItems().list(
                part="contentDetails",
                playlistId=uploads_playlist,
                maxResults=50,
                pageToken=page_token,
            ),
            quota,
            "playlistItems.list",
        )
        for item in resp.get("items", []):
            video_ids.append(item["contentDetails"]["videoId"])
        print(f"  fetched {len(video_ids)} video IDs...", end="\r", flush=True)
        if limit and len(video_ids) >= limit:
            video_ids = video_ids[:limit]
            break
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    print(f"  fetched {len(video_ids)} video IDs.      ")
    return video_ids


def fetch_videos(youtube, quota, video_ids):
    videos = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        resp = execute_with_retry(
            youtube.videos().list(part="snippet,status", id=",".join(chunk)),
            quota,
            "videos.list",
        )
        videos.extend(resp.get("items", []))
        print(f"  loaded {len(videos)}/{len(video_ids)} descriptions...",
              end="\r", flush=True)
    print(f"  loaded {len(videos)}/{len(video_ids)} descriptions.      ")
    return videos


# --------------------------------------------------------------------------
# Snippet handling for videos.update
# --------------------------------------------------------------------------

# Fields returned inside snippet that are read-only and must not be sent back.
READONLY_SNIPPET_FIELDS = {
    "publishedAt",
    "channelId",
    "channelTitle",
    "thumbnails",
    "liveBroadcastContent",
    "localized",
}

# Minimal body used only if the full body is rejected by the API.
CONSERVATIVE_SNIPPET_FIELDS = (
    "title",
    "description",
    "categoryId",
    "tags",
    "defaultLanguage",
)


def build_update_snippet(snippet, new_description, conservative=False):
    """Copy the existing snippet verbatim, drop read-only fields, and change
    ONLY the description. Nothing else is touched."""
    if conservative:
        body = {k: snippet[k] for k in CONSERVATIVE_SNIPPET_FIELDS if k in snippet}
    else:
        body = {k: v for k, v in snippet.items() if k not in READONLY_SNIPPET_FIELDS}
    body["description"] = new_description
    # videos.update requires these two to be present.
    body.setdefault("title", snippet.get("title", ""))
    body.setdefault("categoryId", snippet.get("categoryId", "22"))
    return body


def update_description(youtube, quota, video, new_description):
    from googleapiclient.errors import HttpError

    snippet = video["snippet"]
    for conservative in (False, True):
        body = {
            "id": video["id"],
            "snippet": build_update_snippet(snippet, new_description, conservative),
        }
        try:
            return execute_with_retry(
                youtube.videos().update(part="snippet", body=body),
                quota,
                "videos.update",
            )
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            if not conservative and status == 400:
                print("    full snippet rejected; retrying with minimal snippet fields")
                continue
            raise


# ==========================================================================
# ANALYSIS
# ==========================================================================


def analyse(videos):
    """Split the fetched videos into those needing a change and those not."""
    to_change, unchanged, oversize, bare_only = [], [], [], []

    for v in videos:
        snippet = v["snippet"]
        original = snippet.get("description", "") or ""
        new_desc, hits = apply_replacements(original)
        bare = find_bare_mentions(original)

        record = {
            "video_id": v["id"],
            "title": snippet.get("title", ""),
            "privacy": v.get("status", {}).get("privacyStatus", "unknown"),
            "original_description": original,
            "new_description": new_desc,
            "hits": hits,
            "bare_mentions": bare,
            "has_localized_description": bool(
                snippet.get("localized", {}).get("description")
                and snippet["localized"]["description"] != original
            ),
        }

        if new_desc != original:
            if len(new_desc) > MAX_DESCRIPTION_LENGTH:
                oversize.append(record)
            else:
                to_change.append(record)
        else:
            if bare:
                bare_only.append(record)
            unchanged.append(record)

    return to_change, unchanged, oversize, bare_only


# ==========================================================================
# PREVIEW
# ==========================================================================


def print_preview(channel, video_ids, videos, to_change, unchanged, oversize,
                  bare_only, progress, quota, show_all):
    missing = len(video_ids) - len(videos)
    already_done = [r for r in to_change if r["video_id"] in progress["completed"]]
    pending = [r for r in to_change if r["video_id"] not in progress["completed"]]

    print()
    print("=" * 78)
    print("PREVIEW / DRY RUN - nothing on YouTube has been or will be modified")
    print("=" * 78)
    print(f"Channel : {channel['title']}  ({channel['id']})")
    print(f"Replace : @{OLD_HANDLE}              ->  @{NEW_HANDLE}")
    print(f"          instagram.com/{OLD_HANDLE} ->  instagram.com/{NEW_HANDLE}")
    print()

    limit = len(to_change) if show_all else 25
    for idx, rec in enumerate(to_change, 1):
        if idx > limit:
            print(f"... and {len(to_change) - limit} more. "
                  f"Re-run with --show-all to see every one.")
            break
        done = ("  [ALREADY UPDATED IN A PREVIOUS RUN]"
                if rec["video_id"] in progress["completed"] else "")
        print("-" * 78)
        print(f"[{idx}] {rec['title']}")
        print(f"    https://www.youtube.com/watch?v={rec['video_id']}"
              f"  ({rec['privacy']}){done}")
        for sn in context_snippets(rec["original_description"], rec["new_description"]):
            print(f"    rule   : {sn['rule']}")
            print(f"    BEFORE : {sn['before']}")
            print(f"    AFTER  : {sn['after']}")
        if rec["bare_mentions"]:
            print(f"    NOTE   : also contains bare '{OLD_HANDLE}' text "
                  f"that will NOT be changed.")
        if rec["has_localized_description"]:
            print("    NOTE   : this video has a translated description; "
                  "translations are not modified.")

    if oversize:
        print("-" * 78)
        print("SKIPPED - the new description would exceed YouTube's 5000-character limit:")
        for rec in oversize:
            print(f"    {rec['video_id']}  {rec['title']}  "
                  f"({len(rec['new_description'])} chars)")

    if bare_only:
        print("-" * 78)
        print(f"FYI - these videos mention '{OLD_HANDLE}' without an '@' and "
              f"without an instagram.com URL.")
        print("      They will NOT be changed. Review them by hand if you want to.")
        for rec in bare_only[:20]:
            print(f"    {rec['video_id']}  {rec['title']}")
        if len(bare_only) > 20:
            print(f"    ... and {len(bare_only) - 20} more")

    print("=" * 78)
    print(f"Total videos scanned: {len(videos)}")
    print(f"Videos containing old Instagram: {len(to_change) + len(oversize)}")
    print(f"Videos that would be changed: {len(pending)}")
    if already_done:
        print(f"  (of which {len(already_done)} were already updated in a "
              f"previous run and will be skipped)")
    if oversize:
        print(f"Videos skipped (would exceed 5000 chars): {len(oversize)}")
    if missing > 0:
        print(f"Videos in the uploads playlist that could not be loaded: {missing}")
    print(f"Videos with no change needed: {len(unchanged)}")
    print()

    cost = len(pending) * QUOTA_COST["videos.update"]
    affordable = quota.remaining() // QUOTA_COST["videos.update"]
    print(f"Quota: {quota.summary()}")
    print(f"Updating {len(pending)} videos costs {cost} units "
          f"({QUOTA_COST['videos.update']} units each).")
    if affordable and len(pending) > affordable:
        sessions = -(-len(pending) // affordable)
        print(f"That is more than today's remaining budget. About {affordable} videos "
              f"can be updated now;")
        print(f"the rest resume on later days (roughly {sessions} sessions in total).")
        print("Progress is checkpointed after every single video, so nothing is redone.")
    print("=" * 78)
    print()

    return pending


# ==========================================================================
# BACKUP
# ==========================================================================


def write_backup(records, channel):
    """Write the backup and verify it by reading it back. Returns True on
    success. Any failure must cancel the update."""
    payload = {
        "created_at": now_iso(),
        "channel_id": channel["id"],
        "channel_title": channel["title"],
        "old_handle": OLD_HANDLE,
        "new_handle": NEW_HANDLE,
        "video_count": len(records),
        "videos": [
            {
                "video_id": r["video_id"],
                "title": r["title"],
                "original_description": r["original_description"],
                "new_description": r["new_description"],
            }
            for r in records
        ],
    }

    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        copy_path = os.path.join(BACKUP_DIR, f"backup-{stamp}.json")

        atomic_write_json(BACKUP_FILE, payload)
        atomic_write_json(copy_path, payload)

        # Verify: read it back and compare every description character by character.
        with open(BACKUP_FILE, "r", encoding="utf-8") as fh:
            verify = json.load(fh)
        if verify["video_count"] != len(records):
            raise ValueError("backup video_count mismatch")
        if len(verify["videos"]) != len(records):
            raise ValueError("backup video list length mismatch")
        for saved, rec in zip(verify["videos"], records):
            if saved["video_id"] != rec["video_id"]:
                raise ValueError(f"backup id mismatch for {rec['video_id']}")
            if saved["original_description"] != rec["original_description"]:
                raise ValueError(f"backup description mismatch for {rec['video_id']}")

        size = os.path.getsize(BACKUP_FILE)
        print(f"Backup written and verified: {BACKUP_FILE} "
              f"({size:,} bytes, {len(records)} videos)")
        print(f"Timestamped copy: {copy_path}")
        return True
    except Exception as exc:
        print(f"ERROR: backup failed ({exc}). UPDATE CANCELLED - nothing was changed.")
        return False


# ==========================================================================
# UPDATE MODE
# ==========================================================================


def confirm_update(pending_count, channel, max_updates):
    planned = min(pending_count, max_updates)
    print("!" * 78)
    print(f"You are about to modify {planned} YouTube video descriptions.")
    print(f"Channel: {channel['title']} ({channel['id']})")
    if max_updates < pending_count:
        print(f"(Capped at {max_updates} this run by the daily API quota; "
              f"{pending_count - max_updates} will remain for the next run.)")
    print("Only the description field will be changed. Titles, tags, category,")
    print("privacy, thumbnails and settings are copied through unchanged.")
    print("!" * 78)
    answer = input("Type exactly  UPDATE  to proceed (anything else cancels): ")
    if answer != "UPDATE":
        print("Cancelled. Nothing was modified.")
        return False
    return True


def run_updates(youtube, quota, progress, all_videos, pending, max_updates,
                should_stop=None, on_event=None):
    """Iterate every scanned video so the [n/total] counter matches the
    channel, printing Updated / Skipped for each.

    `should_stop` is an optional zero-argument callable; when it returns True
    the loop finishes early (used by the web UI's Stop button).
    `on_event(kind, info)` is an optional callback, kind being one of
    "updated" / "skipped" / "failed" / "stopped". Both default to None, in
    which case behaviour is identical to the plain command-line run."""
    pending_ids = {r["video_id"]: r for r in pending}
    total = len(all_videos)
    updated = failed = skipped = 0
    budget_stop = False

    def emit(kind, **info):
        if on_event:
            on_event(kind, info)

    for i, v in enumerate(all_videos, 1):
        vid = v["id"]
        title = v["snippet"].get("title", "")
        label = f"[{i}/{total}]"

        if should_stop and should_stop():
            budget_stop = True
            print(f"{label} Stopping: cancelled by user.")
            emit("stopped", reason="cancelled by user")
            break

        if vid in progress["completed"]:
            skipped += 1
            print(f"{label} Skipped: already updated in a previous run - {title}")
            emit("skipped", index=i, total=total, video_id=vid, title=title,
                 reason="already updated in a previous run")
            continue

        rec = pending_ids.get(vid)
        if rec is None:
            skipped += 1
            print(f"{label} Skipped: old Instagram not found")
            emit("skipped", index=i, total=total, video_id=vid, title=title,
                 reason="old Instagram not found")
            continue

        if updated >= max_updates:
            budget_stop = True
            print(f"{label} Stopping: reached this run's update limit ({max_updates}).")
            emit("stopped", reason=f"reached this run's update limit ({max_updates})")
            break

        if not quota.can_afford("videos.update"):
            budget_stop = True
            print(f"{label} Stopping: daily API quota budget exhausted.")
            emit("stopped", reason="daily API quota budget exhausted")
            break

        try:
            update_description(youtube, quota, v, rec["new_description"])
        except QuotaExceeded:
            budget_stop = True
            print(f"{label} Stopping: YouTube reported the daily quota is exhausted.")
            save_progress(progress)
            emit("stopped", reason="YouTube reported the daily quota is exhausted")
            break
        except Exception as exc:
            failed += 1
            progress["failed"][vid] = {"title": title, "error": str(exc), "at": now_iso()}
            save_progress(progress)
            print(f"{label} FAILED: {title}")
            print(f"          {exc}")
            emit("failed", index=i, total=total, video_id=vid, title=title,
                 error=str(exc))
            continue

        updated += 1
        progress["completed"][vid] = {"title": title, "updated_at": now_iso()}
        progress["failed"].pop(vid, None)
        save_progress(progress)  # checkpoint after EVERY successful update
        print(f"{label} Updated: {title}")
        emit("updated", index=i, total=total, video_id=vid, title=title)

    save_progress(progress)
    return updated, skipped, failed, budget_stop


# ==========================================================================
# MAIN
# ==========================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Safely replace an old Instagram handle in YouTube video descriptions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--self-test", action="store_true",
                        help="Run the text-replacement tests only. No network, no credentials.")
    parser.add_argument("--preview-only", action="store_true",
                        help="Preview and exit without offering to update.")
    parser.add_argument("--show-all", action="store_true",
                        help="Show every proposed change instead of the first 25.")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Only look at the N most recent uploads (good for a first test).")
    parser.add_argument("--max-updates", type=int, default=None, metavar="N",
                        help="Update at most N videos this run (default: as many as quota allows).")
    parser.add_argument("--reset-progress", action="store_true",
                        help="Delete the checkpoint file and start over.")
    args = parser.parse_args()

    if args.self_test:
        sys.exit(run_self_test())

    if args.reset_progress:
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
            print(f"Deleted {PROGRESS_FILE}.")
        else:
            print("No progress file to delete.")
        return

    # Fail fast if the replacement rules are broken.
    if run_self_test(verbose=False) != 0:
        print("Refusing to continue with failing replacement tests.")
        sys.exit(1)
    print(f"Replacement self-test passed ({len(SELF_TEST_CASES)} cases).")

    progress = load_progress()
    quota = QuotaTracker(progress)
    print(quota.summary())

    youtube = build_service()

    print("Looking up your channel...")
    channel = get_channel(youtube, quota)
    print(f"  Channel: {channel['title']}  ({channel['id']})")

    print("Listing uploads...")
    video_ids = list_upload_video_ids(youtube, quota, channel["uploads_playlist"], args.limit)

    print("Reading descriptions...")
    videos = fetch_videos(youtube, quota, video_ids)

    to_change, unchanged, oversize, bare_only = analyse(videos)
    pending = print_preview(channel, video_ids, videos, to_change, unchanged,
                            oversize, bare_only, progress, quota, args.show_all)
    save_progress(progress)

    if args.preview_only:
        print("Preview-only mode. Nothing was modified.")
        return

    if not pending:
        print("Nothing left to update. Done.")
        return

    if not sys.stdin.isatty():
        print("Not an interactive terminal, so update mode is unavailable. "
              "Nothing was modified.")
        return

    answer = input("Do you want to proceed to UPDATE mode? (yes/no): ").strip().lower()
    if answer not in ("yes", "y"):
        print("Stopping here. Nothing was modified.")
        return

    affordable = quota.remaining() // QUOTA_COST["videos.update"]
    max_updates = affordable if args.max_updates is None else min(args.max_updates, affordable)
    if max_updates <= 0:
        print("No quota budget left today. Try again after the quota resets "
              "(midnight Pacific Time). Your progress is saved.")
        return

    if not confirm_update(len(pending), channel, max_updates):
        return

    print("\nCreating backup before any change...")
    if not write_backup(pending, channel):
        sys.exit(1)

    print("\nStarting updates. Press Ctrl+C at any time; "
          "progress is saved after every video.\n")
    try:
        updated, skipped, failed, budget_stop = run_updates(
            youtube, quota, progress, videos, pending, max_updates
        )
    except KeyboardInterrupt:
        save_progress(progress)
        print("\nInterrupted. Progress saved. Re-run the script to continue "
              "where you left off.")
        return

    print()
    print("=" * 78)
    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")
    print(f"Failed:  {failed}")
    print(quota.summary())
    remaining = len([r for r in pending if r["video_id"] not in progress["completed"]])
    if remaining:
        print(f"Still to do: {remaining} videos.")
        if budget_stop:
            print("The daily quota is the limit. Run the script again after midnight")
            print("Pacific Time and it will resume automatically.")
        else:
            print("Run the script again to retry them.")
    else:
        print("All matching videos have been updated.")
    print("=" * 78)


if __name__ == "__main__":
    main()
