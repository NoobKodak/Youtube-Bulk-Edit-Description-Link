#!/usr/bin/env python3
"""
yt-dlp wrapper.

Why this exists: the YouTube Data API gives you only 10,000 quota units a day,
and a single description write costs 50 of them. Reading through yt-dlp costs
nothing at all. So this module handles every READ we can push off the API
(titles, descriptions, view counts, likes, thumbnails), leaving the whole
daily quota free for WRITES.

What yt-dlp can and cannot see:
  * it sees public and unlisted videos, and gives view/like counts that the
    API would otherwise charge quota for
  * it cannot see private videos unless you pass browser cookies
  * it cannot write anything - all edits still go through main.py and the API

Standalone use:

    python ytdlp.py --list                  # fast channel listing
    python ytdlp.py --sync                  # full metadata for every video
    python ytdlp.py --export                # write CSV + JSON
    python ytdlp.py --thumbnails            # download every thumbnail
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.environ.get("TOOLKIT_YTDLP", os.path.join(HERE, "yt-dlp.exe"))
CACHE_FILE = "ytdlp_cache.json"
THUMB_DIR = "thumbnails"

# Fields worth keeping. yt-dlp returns ~78 per video; storing them all would
# make the cache enormous for no benefit.
KEEP = (
    "id", "title", "description", "duration", "view_count", "like_count",
    "comment_count", "upload_date", "availability", "thumbnail",
    "webpage_url", "categories", "tags", "channel_id", "channel",
    "was_live", "live_status", "age_limit",
)


class YtDlpError(RuntimeError):
    pass


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ==========================================================================
# LOCATING THE EXECUTABLE
# ==========================================================================


def exe_path(explicit=None):
    """Prefer the copy sitting next to this script, then anything on PATH."""
    if explicit and os.path.exists(explicit):
        return explicit
    if os.path.exists(EXE):
        return EXE
    for name in ("yt-dlp.exe", "yt-dlp"):
        for d in os.environ.get("PATH", "").split(os.pathsep):
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return None


def available(explicit=None):
    return exe_path(explicit) is not None


def version(explicit=None):
    p = exe_path(explicit)
    if not p:
        return None
    try:
        out = subprocess.run([p, "--version"], capture_output=True, text=True,
                             timeout=30, encoding="utf-8", errors="replace")
        return out.stdout.strip() or None
    except Exception:
        return None


def _base_cmd(explicit=None, cookies_browser=None):
    p = exe_path(explicit)
    if not p:
        raise YtDlpError(
            "yt-dlp.exe not found. Put it next to these scripts, or download it "
            "from https://github.com/yt-dlp/yt-dlp/releases")
    cmd = [p, "--no-warnings", "--no-progress", "--ignore-errors",
           "--no-playlist-reverse"]
    if cookies_browser:
        # Lets yt-dlp see private / members-only videos.
        cmd += ["--cookies-from-browser", cookies_browser]
    return cmd


def _run_stream(cmd, on_line, on_stderr=None):
    """Run yt-dlp, yielding stdout lines as they arrive."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1, **kwargs)
    try:
        for line in proc.stdout:
            line = line.strip()
            if line:
                on_line(line)
    finally:
        proc.stdout.close()
        err = proc.stderr.read()
        proc.stderr.close()
        code = proc.wait()
    if on_stderr and err.strip():
        on_stderr(err.strip())
    return code


# ==========================================================================
# CACHE
# ==========================================================================


def load_cache(path=CACHE_FILE):
    if not os.path.exists(path):
        return {"updated_at": None, "channel": None, "videos": {}}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        d.setdefault("videos", {})
        return d
    except Exception:
        return {"updated_at": None, "channel": None, "videos": {}}


def save_cache(cache, path=CACHE_FILE):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def trim(entry):
    out = {k: entry.get(k) for k in KEEP if k in entry}
    out["fetched_at"] = now_iso()
    return out


# ==========================================================================
# READING
# ==========================================================================


def channel_url(channel_id):
    return f"https://www.youtube.com/channel/{channel_id}/videos"


def list_channel(channel_id, exe=None, cookies_browser=None, on_log=None):
    """Fast, flat listing: IDs, titles, durations. A few seconds for a whole
    channel, and it costs no API quota. No descriptions in this mode."""
    log = on_log or (lambda m: None)
    cmd = _base_cmd(exe, cookies_browser) + [
        "--flat-playlist", "--dump-single-json", channel_url(channel_id)]
    chunks = []
    log("Listing channel with yt-dlp (free, no API quota)...")
    code = _run_stream(cmd, chunks.append, lambda e: log(f"yt-dlp: {e[:400]}"))
    if not chunks:
        raise YtDlpError(f"yt-dlp returned nothing (exit {code}).")
    data = json.loads("".join(chunks))
    entries = [e for e in (data.get("entries") or []) if e and e.get("id")]
    log(f"Found {len(entries)} videos on the public channel page.")
    return {
        "channel": data.get("channel") or data.get("title"),
        "channel_id": data.get("channel_id") or channel_id,
        "entries": [{"id": e["id"], "title": e.get("title"),
                     "duration": e.get("duration"),
                     "timestamp": e.get("timestamp")} for e in entries],
    }


def fetch_metadata(video_ids, exe=None, cookies_browser=None,
                   on_progress=None, on_log=None, should_stop=None):
    """Full metadata for each ID, one JSON object per line as it arrives.
    About 1 second per video. Returns {video_id: trimmed_metadata}."""
    log = on_log or (lambda m: None)
    ids = list(video_ids)
    if not ids:
        return {}

    urls = [f"https://www.youtube.com/watch?v={v}" for v in ids]
    batch = os.path.join(os.environ.get("TOOLKIT_DATA_DIR", HERE), ".ytdlp_batch.txt")
    with open(batch, "w", encoding="utf-8") as fh:
        fh.write("\n".join(urls))

    out = {}
    started = time.time()

    def handle(line):
        if not line.startswith("{"):
            return
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            return
        vid = d.get("id")
        if not vid:
            return
        out[vid] = trim(d)
        n = len(out)
        if on_progress:
            elapsed = time.time() - started
            rate = n / elapsed if elapsed else 0
            on_progress({"done": n, "total": len(ids),
                         "eta_seconds": int((len(ids) - n) / rate) if rate else None,
                         "current": d.get("title") or vid})
        if n % 25 == 0 or n == len(ids):
            log(f"  {n}/{len(ids)} videos read")
        if should_stop and should_stop():
            raise KeyboardInterrupt

    cmd = _base_cmd(exe, cookies_browser) + [
        "--dump-json", "--skip-download", "--batch-file", batch]
    log(f"Reading full metadata for {len(ids)} videos (free, ~1s each)...")
    try:
        _run_stream(cmd, handle, lambda e: log(f"yt-dlp: {e[:400]}"))
    except KeyboardInterrupt:
        log("Stopped early by request.")
    finally:
        try:
            os.remove(batch)
        except OSError:
            pass

    missing = [v for v in ids if v not in out]
    if missing:
        log(f"{len(missing)} video(s) could not be read - normally these are "
            f"private. Pass browser cookies to include them.")
    return out


def sync(channel_id, exe=None, cookies_browser=None, on_progress=None,
         on_log=None, should_stop=None, only_missing=False, extra_ids=()):
    """List the channel, fetch metadata, and merge into the cache."""
    log = on_log or print
    cache = load_cache()
    listing = list_channel(channel_id, exe, cookies_browser, log)

    ids = [e["id"] for e in listing["entries"]]
    for v in extra_ids:                       # e.g. private IDs from the API
        if v not in ids:
            ids.append(v)
    if only_missing:
        ids = [v for v in ids if v not in cache["videos"]]
        log(f"{len(ids)} video(s) not yet cached.")

    fetched = fetch_metadata(ids, exe, cookies_browser, on_progress, log, should_stop)
    cache["videos"].update(fetched)
    cache["channel"] = listing["channel"]
    cache["channel_id"] = listing["channel_id"]
    cache["updated_at"] = now_iso()
    save_cache(cache)
    log(f"Cache updated: {len(cache['videos'])} videos in {CACHE_FILE}.")
    return cache


# ==========================================================================
# DERIVED STATS
# ==========================================================================


def summarise(cache):
    vids = list(cache.get("videos", {}).values())
    if not vids:
        return {"count": 0}
    views = [v.get("view_count") or 0 for v in vids]
    likes = [v.get("like_count") or 0 for v in vids]
    durs = [v.get("duration") or 0 for v in vids]
    total_views = sum(views)
    ranked = sorted(vids, key=lambda v: v.get("view_count") or 0, reverse=True)

    def brief(v):
        return {"id": v.get("id"), "title": v.get("title"),
                "view_count": v.get("view_count") or 0,
                "like_count": v.get("like_count") or 0}

    return {
        "count": len(vids),
        "total_views": total_views,
        "total_likes": sum(likes),
        "avg_views": round(total_views / len(vids), 1),
        "median_views": sorted(views)[len(views) // 2],
        "max_views": max(views),
        "total_duration_hours": round(sum(durs) / 3600, 1),
        "engagement_pct": round(sum(likes) / total_views * 100, 2) if total_views else 0,
        "top": [brief(v) for v in ranked[:10]],
        "bottom": [brief(v) for v in ranked[-10:]][::-1],
        "updated_at": cache.get("updated_at"),
    }


# ==========================================================================
# EXPORT
# ==========================================================================


CSV_COLUMNS = ("id", "title", "upload_date", "view_count", "like_count",
               "duration", "availability", "description_length",
               "webpage_url", "description")


def export_csv(cache, path="channel_export.csv"):
    rows = sorted(cache.get("videos", {}).values(),
                  key=lambda v: v.get("upload_date") or "", reverse=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLUMNS)
        for v in rows:
            desc = v.get("description") or ""
            w.writerow([v.get("id"), v.get("title"), v.get("upload_date"),
                        v.get("view_count"), v.get("like_count"),
                        v.get("duration"), v.get("availability"), len(desc),
                        v.get("webpage_url"), desc])
    return path, len(rows)


def export_json(cache, path="channel_export.json"):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return path, len(cache.get("videos", {}))


def download_thumbnails(video_ids, exe=None, cookies_browser=None,
                        outdir=THUMB_DIR, on_log=None):
    log = on_log or print
    os.makedirs(outdir, exist_ok=True)
    urls = [f"https://www.youtube.com/watch?v={v}" for v in video_ids]
    batch = os.path.join(os.environ.get("TOOLKIT_DATA_DIR", HERE), ".ytdlp_thumbs.txt")
    with open(batch, "w", encoding="utf-8") as fh:
        fh.write("\n".join(urls))
    cmd = _base_cmd(exe, cookies_browser) + [
        "--skip-download", "--write-thumbnail", "--convert-thumbnails", "jpg",
        "-o", os.path.join(outdir, "%(id)s.%(ext)s"), "--batch-file", batch]
    log(f"Downloading {len(urls)} thumbnails into {outdir}/ ...")
    _run_stream(cmd, lambda l: None, lambda e: log(f"yt-dlp: {e[:300]}"))
    try:
        os.remove(batch)
    except OSError:
        pass
    got = len([f for f in os.listdir(outdir) if f.lower().endswith(".jpg")])
    log(f"{got} thumbnails now in {outdir}/.")
    return got


# ==========================================================================
# CLI
# ==========================================================================


def _channel_id_from_token():
    """Reuse the channel already discovered by main.py, if there is one."""
    cache = load_cache()
    if cache.get("channel_id"):
        return cache["channel_id"]
    return None


def cli():
    ap = argparse.ArgumentParser(description="yt-dlp powered channel reader (no API quota).")
    ap.add_argument("--channel", help="Channel ID (UC...). Defaults to the cached one.")
    ap.add_argument("--list", action="store_true", help="Fast flat listing.")
    ap.add_argument("--sync", action="store_true", help="Fetch full metadata into the cache.")
    ap.add_argument("--only-missing", action="store_true", help="With --sync, skip cached videos.")
    ap.add_argument("--export", action="store_true", help="Write channel_export.csv and .json.")
    ap.add_argument("--thumbnails", action="store_true", help="Download every thumbnail.")
    ap.add_argument("--stats", action="store_true", help="Print channel statistics.")
    ap.add_argument("--cookies-from-browser", metavar="BROWSER",
                    help="chrome/edge/firefox - needed to include private videos.")
    args = ap.parse_args()

    v = version()
    if not v:
        print("yt-dlp.exe not found next to this script or on PATH.")
        sys.exit(1)
    print(f"yt-dlp {v}")

    channel = args.channel or _channel_id_from_token()
    if not channel and (args.list or args.sync or args.thumbnails):
        print("No channel ID. Pass --channel UCxxxx (run main.py once to discover it).")
        sys.exit(1)

    if args.list:
        listing = list_channel(channel, cookies_browser=args.cookies_from_browser)
        print(f"{listing['channel']}: {len(listing['entries'])} videos")
        for e in listing["entries"][:20]:
            print(f"  {e['id']}  {str(e['title'])[:64]}")
        if len(listing["entries"]) > 20:
            print(f"  ... and {len(listing['entries']) - 20} more")

    if args.sync:
        def prog(p):
            print(f"  {p['done']}/{p['total']}  eta {p['eta_seconds']}s   ",
                  end="\r", flush=True)
        sync(channel, cookies_browser=args.cookies_from_browser,
             on_progress=prog, only_missing=args.only_missing)
        print()

    if args.stats:
        s = summarise(load_cache())
        if not s.get("count"):
            print("Cache is empty. Run --sync first.")
        else:
            print(f"  videos           : {s['count']}")
            print(f"  total views      : {s['total_views']:,}")
            print(f"  total likes      : {s['total_likes']:,}")
            print(f"  average views    : {s['avg_views']:,}")
            print(f"  median views     : {s['median_views']:,}")
            print(f"  like rate        : {s['engagement_pct']}%")
            print(f"  total runtime    : {s['total_duration_hours']} hours")
            print("  top 5 by views:")
            for t in s["top"][:5]:
                print(f"    {t['view_count']:>7,}  {str(t['title'])[:58]}")

    if args.export:
        cache = load_cache()
        p1, n1 = export_csv(cache)
        p2, _ = export_json(cache)
        print(f"  wrote {p1} ({n1} rows) and {p2}")

    if args.thumbnails:
        cache = load_cache()
        ids = list(cache.get("videos", {})) or [
            e["id"] for e in list_channel(channel)["entries"]]
        download_thumbnails(ids, cookies_browser=args.cookies_from_browser)

    if not any([args.list, args.sync, args.export, args.thumbnails, args.stats]):
        ap.print_help()


if __name__ == "__main__":
    cli()
