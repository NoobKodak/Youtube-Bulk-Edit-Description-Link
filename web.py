#!/usr/bin/env python3
"""
Channel Toolkit - local web UI.

    python web.py

Serves a dashboard on http://127.0.0.1:8765 and opens your browser.

Architecture, and the reason for it:

    reads  -> yt-dlp   (ytdlp.py)   free, unlimited, but cannot see private
                                    videos without cookies and cannot write
    writes -> YouTube API (main.py) 50 quota units each, 10,000 per day

So every read we can push onto yt-dlp leaves more of the daily quota for the
only thing that actually needs it: changing descriptions.

This file is a front-end only. Every rule, safety check, backup and checkpoint
lives in main.py / bulkedit.py / fix_oversize.py, and the command-line tools
share the same update_progress.json. Nothing is written to YouTube until you
type UPDATE in the confirm dialog.

Listens on 127.0.0.1 only, so it is not reachable from your network.
"""

from __future__ import annotations

import io
import hashlib
import difflib
import secrets
import json
import mimetypes
import os
import sys
import threading
import webbrowser
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import bulkedit
import download
import main
import ytdlp

HOST, PORT = "127.0.0.1", int(os.environ.get("TOOLKIT_PORT", "8765"))
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("TOOLKIT_DATA_DIR", HERE)
os.makedirs(DATA_DIR, exist_ok=True)
os.chdir(DATA_DIR)
ACCESS_TOKEN = os.environ.get("TOOLKIT_ACCESS_TOKEN", "")

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ==========================================================================
# SHARED STATE
# ==========================================================================

LOCK = threading.RLock()

STATE = {
    "phase": "idle",      # idle | scanning | syncing | updating | ready | error
    "message": "Ready.",
    "error": None,
    "channel": None,
    "job": None,          # {label, done, total, eta_seconds, current}
    "stop": False,
    "download": None,
}

LOG: list[dict] = []
API_VIDEOS: list[dict] = []      # raw videos.list items - the only source we can write from
# A preview is an explicit approval boundary: Apply may only use this exact
# snapshot, never a newly calculated channel-wide set of videos.
BULK_PREVIEW: dict | None = None


def log(text):
    with LOCK:
        for line in str(text).rstrip("\n").split("\n"):
            line = line.split("\r")[-1]
            if line.strip():
                LOG.append({"n": len(LOG) + 1, "text": line})
        del LOG[:-4000]


class LogWriter(io.TextIOBase):
    """Captures print() from main.py so the CLI output shows up in the UI."""

    def __init__(self):
        self._buf = ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            log(line)
        return len(s)

    def flush(self):
        pass


def set_phase(phase, message=None, error=None):
    with LOCK:
        STATE["phase"] = phase
        if message is not None:
            STATE["message"] = message
        STATE["error"] = error


def set_job(label=None, done=0, total=0, eta=None, current=""):
    with LOCK:
        STATE["job"] = None if label is None else {
            "label": label, "done": done, "total": total,
            "eta_seconds": eta, "current": current}


def busy():
    return STATE["phase"] in ("scanning", "syncing", "updating", "downloading")


def should_stop():
    with LOCK:
        return STATE["stop"]


def start(fn, *a):
    with LOCK:
        STATE["stop"] = False
    t = threading.Thread(target=fn, args=a, daemon=True)
    t.start()
    return t


# ==========================================================================
# MERGED VIDEO VIEW
# ==========================================================================


def merged_videos():
    """One row per video, combining what the API knows (privacy, authoritative
    description) with what yt-dlp knows (views, likes, duration)."""
    cache = ytdlp.load_cache()["videos"]
    rows, seen = [], set()

    for v in API_VIDEOS:
        vid = v["id"]
        seen.add(vid)
        sn = v["snippet"]
        y = cache.get(vid, {})
        desc = sn.get("description") or ""
        rows.append({
            "id": vid,
            "title": sn.get("title") or y.get("title") or "",
            "description": desc,
            "desc_len": bulkedit.measured_len(desc),
            "privacy": v.get("status", {}).get("privacyStatus", "unknown"),
            "views": y.get("view_count"),
            "likes": y.get("like_count"),
            "duration": y.get("duration"),
            "upload_date": y.get("upload_date") or (sn.get("publishedAt") or "")[:10].replace("-", ""),
            "has_thumb": os.path.exists(os.path.join(ytdlp.THUMB_DIR, vid + ".jpg")),
            "source": "api",
        })

    for vid, y in cache.items():
        if vid in seen:
            continue
        desc = y.get("description") or ""
        rows.append({
            "id": vid,
            "title": y.get("title") or "",
            "description": desc,
            "desc_len": bulkedit.measured_len(desc),
            "privacy": y.get("availability") or "public",
            "views": y.get("view_count"),
            "likes": y.get("like_count"),
            "duration": y.get("duration"),
            "upload_date": y.get("upload_date"),
            "has_thumb": os.path.exists(os.path.join(ytdlp.THUMB_DIR, vid + ".jpg")),
            "source": "ytdlp",
        })

    rows.sort(key=lambda r: str(r.get("upload_date") or ""), reverse=True)
    return rows


def count_pending_edits():
    """How many videos the currently enabled rules would change."""
    try:
        compiled, _errs = bulkedit.validate_rules(bulkedit.load_rules())
    except Exception:
        return 0
    if not compiled:
        return 0
    n = 0
    for r in merged_videos():
        new, hits, _rej = bulkedit.apply_rules(r["description"], compiled)
        if hits and new != r["description"]:
            n += 1
    return n


# ==========================================================================
# STATUS
# ==========================================================================


def reset_info():
    now_pt = datetime.now(main.PACIFIC)
    nxt = (now_pt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    local = datetime.now().astimezone()
    return {
        "reset_local": nxt.astimezone(local.tzinfo).strftime("%a %d %b, %H:%M"),
        "seconds_until_reset": int((nxt - now_pt).total_seconds()),
    }


def build_status():
    progress = main.load_progress()
    quota = main.QuotaTracker(progress)
    cache = ytdlp.load_cache()

    with LOCK:
        st = dict(STATE)
        api_n = len(API_VIDEOS)

    try:
        links = len({u for r in merged_videos()
                     for u in bulkedit.extract_urls(r["description"])})
    except Exception:
        links = 0

    return {
        "phase": st["phase"],
        "message": st["message"],
        "error": st["error"],
        "channel": st["channel"],
        "job": st["job"],
        "download": dict(st["download"]) if st.get("download") else None,
        "counts": {
            "videos": len(merged_videos()),
            "api_videos": api_n,
            "completed": len(progress["completed"]),
            "failed": len(progress["failed"]),
            "pending_edits": count_pending_edits(),
            "links": links,
        },
        "quota": {
            "spent": quota.spent,
            "limit": main.DAILY_QUOTA_LIMIT,
            "remaining": quota.remaining(),
            "affordable_updates": quota.remaining() // main.QUOTA_COST["videos.update"],
            "update_cost": main.QUOTA_COST["videos.update"],
        },
        "reset": reset_info(),
        "ytdlp": {
            "available": ytdlp.available(),
            "version": ytdlp.version(),
            "cached": len(cache.get("videos", {})),
            "updated_at": cache.get("updated_at"),
        },
    }


# ==========================================================================
# JOBS
# ==========================================================================


def job_api_scan():
    w = LogWriter()
    try:
        set_phase("scanning", "Signing in and reading your channel through the API...")
        with redirect_stdout(w):
            progress = main.load_progress()
            quota = main.QuotaTracker(progress)
            youtube = main.build_service()
            set_phase("scanning", "Signed in. Finding your channel...")
            channel = main.get_channel(youtube, quota)
            print(f"Channel: {channel['title']} ({channel['id']})")
            set_phase("scanning", "Listing your channel's uploads...")
            ids = main.list_upload_video_ids(youtube, quota, channel["uploads_playlist"])
            set_phase("scanning", f"Reading descriptions for {len(ids)} videos...")
            videos = main.fetch_videos(youtube, quota, ids)
            main.save_progress(progress)

        with LOCK:
            API_VIDEOS[:] = videos
            STATE["channel"] = channel
        log(f"API scan complete: {len(videos)} videos "
            f"({quota.spent_this_run} quota units used).")
        set_phase("ready", f"API scan complete - {len(videos)} videos.")
    except Exception as exc:
        log(f"ERROR during API scan: {exc}")
        set_phase("error", "API scan failed.", str(exc))


def job_ytdlp_sync(cookies_browser):
    try:
        set_phase("syncing", "Reading the channel with yt-dlp (free)...")
        channel_id = None
        with LOCK:
            if STATE["channel"]:
                channel_id = STATE["channel"]["id"]
        if not channel_id:
            channel_id = ytdlp.load_cache().get("channel_id")
        if not channel_id:
            # Ask the API once - it is a single quota unit.
            log("No channel ID cached; asking the API for it (1 quota unit).")
            progress = main.load_progress()
            quota = main.QuotaTracker(progress)
            w = LogWriter()
            with redirect_stdout(w):
                youtube = main.build_service()
                channel = main.get_channel(youtube, quota)
                main.save_progress(progress)
            with LOCK:
                STATE["channel"] = channel
            channel_id = channel["id"]

        # Private videos are invisible to yt-dlp, but if we already did an API
        # scan we know their IDs and can at least try.
        with LOCK:
            extra = [v["id"] for v in API_VIDEOS]

        def prog(p):
            set_job("Reading metadata", p["done"], p["total"],
                    p["eta_seconds"], (p.get("current") or "")[:60])

        ytdlp.sync(channel_id, cookies_browser=cookies_browser,
                   on_progress=prog, on_log=log, should_stop=should_stop,
                   extra_ids=extra)
        set_job(None)
        cache = ytdlp.load_cache()
        set_phase("ready", f"Free sync complete - {len(cache['videos'])} videos cached.")
    except Exception as exc:
        set_job(None)
        log(f"ERROR during yt-dlp sync: {exc}")
        set_phase("error", "yt-dlp sync failed.", str(exc))


def job_thumbnails(cookies_browser):
    try:
        set_phase("syncing", "Downloading thumbnails...")
        ids = list(ytdlp.load_cache().get("videos", {}))
        if not ids:
            set_phase("ready", "Nothing cached yet - run a free sync first.")
            return
        n = ytdlp.download_thumbnails(ids, cookies_browser=cookies_browser, on_log=log)
        set_phase("ready", f"{n} thumbnails downloaded.")
    except Exception as exc:
        log(f"ERROR downloading thumbnails: {exc}")
        set_phase("error", "Thumbnail download failed.", str(exc))


def job_download(opts):
    """Run a yt-dlp download. Nothing here touches the YouTube API or your
    descriptions - it only writes files to disk."""
    try:
        cmd, outdir = download.build_command(opts)
    except download.OptionError as exc:
        set_phase("error", "Those download options are not valid.", str(exc))
        return

    try:
        set_phase("downloading", "Starting download...")
        with LOCK:
            STATE["download"] = {"id": secrets.token_hex(8), "status": "running", "folder": outdir, "percent": None}
        os.makedirs(outdir, exist_ok=True)
        log(f"Output folder: {outdir}")
        log("Command: " + download.describe(cmd))

        def on_prog(p):
            with LOCK:
                STATE["download"].update({"percent": p["percent"], "title": p["title"], "speed": p["speed"], "item": p["item"], "items": p["items"]})
            label = "Downloading"
            if p["items"]:
                label = "Downloading {}/{}".format(p["item"], p["items"])
            detail = "{} {} eta {} - {}".format(
                p["percent"], p["speed"], p["eta"], p["title"])
            set_job(label, p["item"] or 0, p["items"] or 0, None, detail)

        state = download.run(cmd, on_log=log, on_progress=on_prog,
                             should_stop=should_stop)
        set_job(None)

        code = state["exit_code"]
        with LOCK:
            STATE["download"].update({"status": "complete" if code == 0 else "stopped" if STATE["stop"] else "errors", "files": state.get("files", 0)})
        if code == 0:
            set_phase("ready", f"Download finished. Files are in {outdir}")
        else:
            # yt-dlp returns non-zero when any single item failed, which with
            # --ignore-errors can still mean most of them succeeded.
            set_phase("ready",
                      f"Download finished with errors (exit {code}). "
                      f"Check the log. Files are in {outdir}")
    except Exception as exc:
        set_job(None)
        log(f"ERROR during download: {exc}")
        with LOCK:
            if STATE.get("download"):
                STATE["download"].update({"status": "errors", "error": str(exc)})
        set_phase("error", "Download failed.", str(exc))


def description_review(before, after):
    """Group nearby edits, keeping each side's real context and exact marks."""
    groups = []
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    for opcodes in matcher.get_grouped_opcodes(65):
        old_parts, new_parts = [], []
        for tag, a, b, c, d in opcodes:
            if b > a:
                old_parts.append({"text": before[a:b], "changed": tag != "equal"})
            if d > c:
                new_parts.append({"text": after[c:d], "changed": tag != "equal"})
        groups.append({"before": old_parts, "after": new_parts})
    return groups


def compute_preview(video_ids=None):
    """Dry run of the enabled rules. Reads nothing from the network."""
    rules = bulkedit.load_rules()
    compiled, errors = bulkedit.validate_rules(rules)

    with LOCK:
        api_by_id = {v["id"]: v for v in API_VIDEOS}

    rows = merged_videos()
    if video_ids is not None:
        wanted = set(video_ids)
        rows = [r for r in rows if r["id"] in wanted]
    else:
        rows = [r for r in rows if r["id"] in api_by_id]

    progress = main.load_progress()
    quota = main.QuotaTracker(progress)

    changes, rejected, unchanged = [], [], []
    for r in rows:
        old = r["description"]
        new, hits, rej = bulkedit.apply_rules(old, compiled)
        for x in rej:
            rejected.append({"video_id": r["id"], "title": r["title"],
                             "rule": x["rule"], "reason": x["reason"]})
        if not hits or new == old:
            if not rej:
                unchanged.append({"video_id": r["id"], "title": r["title"]})
            continue
        if r["id"] not in api_by_id:
            rejected.append({"video_id": r["id"], "title": r["title"],
                             "rule": "(all)",
                             "reason": "not in the API scan - run an API scan to write it"})
            continue
        changes.append({
            "video_id": r["id"], "title": r["title"], "privacy": r["privacy"],
            "old_len": bulkedit.measured_len(old),
            "new_len": bulkedit.measured_len(new),
            "diffs": bulkedit.diff_snippets(old, new, compiled),
            "before": old, "after": new,
            "edits": description_review(old, new),
            "replacement_count": sum(h["count"] for h in hits),
        })

    pending = []
    for c in changes:
        source = api_by_id[c["video_id"]]
        old = source["snippet"].get("description") or ""
        new, _hits, _rejections = bulkedit.apply_rules(old, compiled)
        pending.append({"video_id": c["video_id"], "title": c["title"],
                        "original_description": old, "new_description": new})
    fingerprint = hashlib.sha256(json.dumps(
        {"rules": rules, "ids": [p["video_id"] for p in pending],
         "before": [p["original_description"] for p in pending]},
        sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {
        "scanned": len(rows),
        "scope": "selected videos" if video_ids else "whole channel",
        "changes": changes,
        "rejected": rejected,
        "errors": errors,
        "unchanged": unchanged,
        "rules_snapshot": rules,
        "affordable": quota.remaining() // main.QUOTA_COST["videos.update"],
        "preview_id": secrets.token_hex(16) + fingerprint[:8],
        "pending": pending,
    }


def job_bulk_apply(preview):
    w = LogWriter()
    try:
        set_phase("updating", "Preparing bulk edit...")
        with LOCK:
            videos = list(API_VIDEOS)
            channel = STATE["channel"]
        pending = preview["pending"]
        if preview["rules_snapshot"] != bulkedit.load_rules() or preview["errors"]:
            set_phase("error", "Settings changed. Preview again before applying.")
            return
        videos_by_id = {v["id"]: v for v in videos}
        changed_since_preview = [p["title"] for p in pending
                                 if p["video_id"] not in videos_by_id or
                                 (videos_by_id[p["video_id"]]["snippet"].get("description") or "")
                                 != p["original_description"]]
        if changed_since_preview:
            set_phase("error", "Descriptions changed since preview.",
                      "Run a new preview before applying changes.")
            return
        if not pending:
            set_phase("ready", "Nothing to change.")
            return

        with redirect_stdout(w):
            print(f"Backing up {len(pending)} descriptions before any change...")
            if not main.write_backup(pending, channel):
                set_phase("error", "Backup failed - nothing was changed.",
                          "Backup could not be written or verified.")
                return

            progress = main.load_progress()
            quota = main.QuotaTracker(progress)
            youtube = main.build_service()
            max_updates = quota.remaining() // main.QUOTA_COST["videos.update"]

            done = {"n": 0}

            def on_event(kind, info):
                if kind == "updated":
                    done["n"] += 1
                    set_job("Updating", done["n"], min(len(pending), max_updates),
                            None, (info.get("title") or "")[:60])

            # main.run_updates skips anything already in progress["completed"],
            # which is not what we want for a *new* rule set: those videos were
            # completed for the Instagram job, not this one. Use a private copy
            # of the checkpoint so the two jobs do not shadow each other.
            edit_progress = {"completed": {}, "failed": progress["failed"],
                             "quota_by_pt_date": progress["quota_by_pt_date"]}

            updated, skipped, failed, stopped = main.run_updates(
                youtube, quota, edit_progress,
                [videos_by_id[p["video_id"]] for p in pending], pending, max_updates,
                should_stop=should_stop, on_event=on_event)

            progress["quota_by_pt_date"] = edit_progress["quota_by_pt_date"]
            progress["failed"] = edit_progress["failed"]
            main.save_progress(progress)

            print(f"Finished. Updated {updated}, failed {failed}.")
            print(main.QuotaTracker(progress).summary())

        # Refresh our in-memory copy so the UI stops offering the same edit.
        with LOCK:
            for v in API_VIDEOS:
                for p in pending:
                    if p["video_id"] == v["id"] and v["id"] in edit_progress["completed"]:
                        v["snippet"]["description"] = p["new_description"]

        set_job(None)
        set_phase("ready", f"Bulk edit finished: {updated} updated, {failed} failed, "
                  f"{max(0, len(pending)-updated-failed)} remaining. Scan and preview again for remaining work.")
    except Exception as exc:
        set_job(None)
        log(f"ERROR during bulk edit: {exc}")
        set_phase("error", "Bulk edit failed.", str(exc))


# ==========================================================================
# HTTP
# ==========================================================================


class Handler(BaseHTTPRequestHandler):
    server_version = "ChannelToolkit/2.0"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _file(self, name, ctype):
        path = os.path.join(HERE, name)
        if not os.path.exists(path):
            return self._send(404, {"error": f"{name} is missing"})
        with open(path, "rb") as fh:
            return self._send(200, fh.read(), ctype)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    # ---- GET ----
    def _authorized(self):
        if ACCESS_TOKEN and not secrets.compare_digest(self.headers.get("X-Toolkit-Token", ""), ACCESS_TOKEN):
            self._send(403, {"error": "Open this workspace through Channel Toolkit desktop."})
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{HOST}:{self.server.server_port}":
            self._send(403, {"error": "Requests from other websites are not allowed."})
            return False
        return True

    def do_GET(self):
        if not self._authorized():
            return
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path

        if p == "/":
            return self._file("ui.html", "text/html; charset=utf-8")
        if p == "/app.js":
            return self._file("app.js", "text/javascript; charset=utf-8")
        brand_assets = {
            "/assets/ui/ui.css": ("assets/ui/ui.css", "text/css; charset=utf-8"),
            "/assets/ui/ui.js": ("assets/ui/ui.js", "text/javascript; charset=utf-8"),
            "/assets/brand.css": ("assets/brand.css", "text/css; charset=utf-8"),
            "/assets/channel-mark.svg": ("assets/channel-mark.svg", "image/svg+xml"),
            "/assets/fonts/LinkSans-LinkSansVF.woff2": ("assets/fonts/LinkSans-LinkSansVF.woff2", "font/woff2"),
            "/assets/fonts/link-sans.css": ("assets/fonts/link-sans.css", "text/css; charset=utf-8"),
        }
        if p in brand_assets:
            return self._file(*brand_assets[p])

        if p == "/thumb":
            vid = (q.get("id") or [""])[0]
            # Guard against path traversal: YouTube IDs are [A-Za-z0-9_-]{11}.
            if not vid or not all(c.isalnum() or c in "-_" for c in vid):
                return self._send(400, {"error": "bad id"})
            fp = os.path.join(DATA_DIR, ytdlp.THUMB_DIR, vid + ".jpg")
            if not os.path.exists(fp):
                return self._send(404, {"error": "no thumbnail"})
            with open(fp, "rb") as fh:
                data = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.types_map.get(".jpg", "image/jpeg"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionAbortedError):
                pass
            return

        if p == "/api/status":
            return self._send(200, build_status())

        if p == "/api/stats":
            return self._send(200, ytdlp.summarise(ytdlp.load_cache()))

        if p == "/api/videos":
            rows = merged_videos()
            # Descriptions can be 5 KB each; 500 of them is 2.5 MB. Send a
            # trimmed copy for the table and let /api/video fetch full text.
            slim = [{k: v for k, v in r.items() if k != "description"}
                    | {"description": (r["description"] or "")[:400]} for r in rows]
            return self._send(200, {"videos": slim, "total": len(rows)})

        if p == "/api/video":
            vid = (q.get("id") or [""])[0]
            for r in merged_videos():
                if r["id"] == vid:
                    return self._send(200, r)
            return self._send(404, {"error": "not found"})

        if p == "/api/rules":
            rules = bulkedit.load_rules()
            compiled, errors = bulkedit.validate_rules(rules)
            return self._send(200, {"rules": rules, "errors": errors,
                                    "enabled": len(compiled)})

        if p == "/api/links":
            rows = merged_videos()
            links = bulkedit.link_report(
                [(r["id"], r["title"], r["description"]) for r in rows])
            for l in links:
                l["domain"] = bulkedit.domain_of(l["url"])
            return self._send(200, {"links": links, "scanned": len(rows)})

        if p == "/api/download/env":
            env = download.environment()
            v = env.get("ytdlp_version") or ""
            # yt-dlp warns past 90 days; a stale build gets HTTP 403 on media.
            env["stale"] = bool(v and v < "2026.06")
            env["presets"] = [{"key": k, "label": d["label"], "hint": d["hint"],
                               "opts": d["opts"]}
                              for k, d in download.PRESETS.items()]
            env["templates"] = download.OUTPUT_TEMPLATES
            env["choices"] = {
                "modes": download.MODES, "containers": download.CONTAINERS,
                "audio_formats": download.AUDIO_FORMATS, "heights": download.HEIGHTS,
                "sponsorblock": download.SPONSORBLOCK, "browsers": download.BROWSERS,
                "sub_convert": download.SUB_CONVERT,
                "filter_fields": download.FILTER_FIELDS,
            }
            return self._send(200, env)

        if p == "/api/log":
            since = int((q.get("since") or ["0"])[0])
            with LOCK:
                lines = [e for e in LOG if e["n"] > since]
                return self._send(200, {"lines": lines[-600:], "total": len(LOG)})

        return self._send(404, {"error": "no such endpoint"})

    # ---- POST ----
    def do_POST(self):
        if not self._authorized():
            return
        global BULK_PREVIEW
        p = urlparse(self.path).path
        body = self._body()

        if p == "/api/scan":
            if busy():
                return self._send(409, {"error": f"already {STATE['phase']}"})
            BULK_PREVIEW = None
            start(job_api_scan)
            return self._send(200, {"ok": True})

        if p == "/api/ytdlp/sync":
            if busy():
                return self._send(409, {"error": f"already {STATE['phase']}"})
            if not ytdlp.available():
                return self._send(400, {"error": "yt-dlp.exe not found next to web.py"})
            start(job_ytdlp_sync, body.get("cookies_browser"))
            return self._send(200, {"ok": True})

        if p == "/api/ytdlp/thumbnails":
            if busy():
                return self._send(409, {"error": f"already {STATE['phase']}"})
            start(job_thumbnails, body.get("cookies_browser"))
            return self._send(200, {"ok": True})

        if p == "/api/rules":
            rules = body.get("rules")
            if not isinstance(rules, list):
                return self._send(400, {"error": "expected a list of rules"})
            compiled, errors = bulkedit.validate_rules(rules)
            bulkedit.save_rules(rules)
            with LOCK:
                BULK_PREVIEW = None
            return self._send(200, {"ok": True, "errors": errors,
                                    "enabled": len(compiled)})

        if p == "/api/bulk/preview":
            try:
                preview = compute_preview(body.get("video_ids"))
                with LOCK:
                    BULK_PREVIEW = preview
                # Pending descriptions are retained on the server only; the browser
                # receives the review information and a short-lived preview ID.
                public = {k: v for k, v in preview.items() if k not in ("pending", "rules_snapshot")}
                return self._send(200, public)
            except Exception as exc:
                return self._send(400, {"error": str(exc)})

        if p == "/api/bulk/apply":
            if busy():
                return self._send(409, {"error": f"already {STATE['phase']}"})
            if body.get("confirm") != "UPDATE":
                return self._send(400, {"error": "you must type UPDATE exactly"})
            with LOCK:
                if not API_VIDEOS:
                    return self._send(400, {"error": "run an API scan first"})
                preview = BULK_PREVIEW
            if not preview or body.get("preview_id") != preview["preview_id"]:
                return self._send(400, {"error": "your preview is no longer current; review it again before applying"})
            if preview["errors"] or preview["rules_snapshot"] != bulkedit.load_rules():
                return self._send(400, {"error": "settings changed or contain errors; run a new preview"})
            progress = main.load_progress()
            quota = main.QuotaTracker(progress)
            if quota.remaining() // main.QUOTA_COST["videos.update"] <= 0:
                return self._send(400, {"error": "no quota budget left today"})
            with LOCK:
                BULK_PREVIEW = None
                STATE["phase"] = "updating"
            start(job_bulk_apply, preview)
            return self._send(200, {"ok": True})

        if p == "/api/export":
            cache = ytdlp.load_cache()
            if not cache.get("videos"):
                return self._send(400, {"error": "nothing cached - run a free sync first"})
            if body.get("format") == "json":
                path, n = ytdlp.export_json(cache)
            else:
                path, n = ytdlp.export_csv(cache)
            log(f"Exported {n} videos to {path}")
            return self._send(200, {"ok": True,
                                    "message": f"Wrote {path} ({n} videos)."})

        if p == "/api/download/preview":
            # Build the command without running it, so the user can read
            # exactly what would happen before committing.
            try:
                cmd, outdir = download.build_command(body)
                return self._send(200, {"ok": True, "outdir": outdir,
                                        "command": download.describe(cmd),
                                        "argv": cmd})
            except download.OptionError as exc:
                return self._send(400, {"error": str(exc)})

        if p == "/api/download/formats":
            try:
                text = download.list_formats(body.get("url"),
                                             cookies_browser=body.get("cookies_browser"))
                return self._send(200, {"ok": True, "text": text})
            except download.OptionError as exc:
                return self._send(400, {"error": str(exc)})
            except Exception as exc:
                return self._send(400, {"error": f"yt-dlp failed: {exc}"})

        if p == "/api/download/open-folder":
            with LOCK:
                folder = (STATE.get("download") or {}).get("folder")
            if not folder or not os.path.isdir(folder):
                return self._send(400, {"error": "Download folder is not available yet."})
            try:
                os.startfile(folder)
            except Exception as exc:
                return self._send(400, {"error": f"Could not open the folder: {exc}"})
            return self._send(200, {"ok": True})

        if p == "/api/download/start":
            if busy():
                return self._send(409, {"error": f"already {STATE['phase']}"})
            if not ytdlp.available():
                return self._send(400, {"error": "yt-dlp.exe not found next to web.py"})
            try:
                download.build_command(body)      # validate before starting
            except download.OptionError as exc:
                return self._send(400, {"error": str(exc)})
            start(job_download, body)
            return self._send(200, {"ok": True})

        if p == "/api/stop":
            with LOCK:
                STATE["stop"] = True
            log("Stop requested - finishing the current item, then halting.")
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "no such endpoint"})


# ==========================================================================
# ENTRY POINT
# ==========================================================================


class Server(ThreadingHTTPServer):
    # Windows lets a second socket bind a port that is already listening, which
    # would silently shadow an older instance and serve a stale page. Refuse
    # instead, so the conflict is obvious.
    allow_reuse_address = False


def port_in_use(host, port):
    import socket
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def run():
    print("=" * 68)
    print("  Channel Toolkit - local web UI")
    print("=" * 68)
    print(f"  Folder  : {HERE}")
    print(f"  URL     : http://{HOST}:{PORT}")
    print(f"  yt-dlp  : {ytdlp.version() or 'NOT FOUND'}")
    print("  Reads are free via yt-dlp; API quota is reserved for writes.")
    print("  Nothing is written to YouTube until you type UPDATE in the page.")
    print("  Ctrl+C here to stop.")
    print("=" * 68)

    if port_in_use(HOST, PORT):
        print(f"\nERROR: something is already listening on {HOST}:{PORT}.")
        print("That is almost certainly an older copy of this app still running.")
        print("Close its PowerShell window (or press Ctrl+C in it) and try again.")
        print("On Windows you can find and stop it with:")
        print(f"  Get-NetTCPConnection -LocalPort {PORT} -State Listen | "
              f"Select-Object OwningProcess")
        print("  Stop-Process -Id <that number>")
        sys.exit(1)

    if main.run_self_test(verbose=False) != 0 or bulkedit.self_test() != 0:
        print("Self-tests FAILED - refusing to start.")
        sys.exit(1)

    log(f"Replacement tests passed ({len(main.SELF_TEST_CASES)} cases).")
    log(f"yt-dlp {ytdlp.version() or 'not found'}")
    log("Ready. 'Sync (free)' reads everything without spending API quota.")

    httpd = Server((HOST, PORT), Handler)
    if os.environ.get("TOOLKIT_DESKTOP"):
        ready = os.path.join(DATA_DIR, "ready-" + ACCESS_TOKEN[:12] + ".json")
        with open(ready, "w", encoding="utf-8") as handle:
            json.dump({"origin": f"http://{HOST}:{httpd.server_port}"}, handle)
    try:
        if not os.environ.get("TOOLKIT_DESKTOP"):
            webbrowser.open(f"http://{HOST}:{PORT}")
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run()
