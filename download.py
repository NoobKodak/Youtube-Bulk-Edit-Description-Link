#!/usr/bin/env python3
"""
Download / archive engine built on yt-dlp.

This is the write-to-disk half of the toolkit. ytdlp.py reads metadata;
this module fetches actual media: video, audio, subtitles, thumbnails,
descriptions and info JSON, with an archive file so nothing is fetched twice.

Everything is assembled into an argument LIST and handed to subprocess without
a shell, and every user-supplied value is checked against an allow-list before
it becomes a flag. A free-text field can never turn into an extra option.

Intended for your own channel, or content you have permission to download.
yt-dlp does not defeat DRM and neither does this.

Standalone use:

    python download.py --self-test
    python download.py --formats "https://www.youtube.com/watch?v=..."
    python download.py --preset audio-mp3 --url "https://..."
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys

import ytdlp

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.environ.get("TOOLKIT_DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTDIR = os.environ.get("TOOLKIT_DOWNLOAD_DIR", "downloads")
ARCHIVE_NAME = "download-archive.txt"

# A sentinel that cannot appear in a title, so progress lines are unambiguous.
PROGRESS_MARK = "@@PROG@@"


# ==========================================================================
# ALLOW-LISTS  (anything not listed here simply cannot be requested)
# ==========================================================================

MODES = ("video", "audio", "metadata", "subtitles", "thumbnails")

CONTAINERS = ("mp4", "mkv", "webm")
AUDIO_FORMATS = ("mp3", "m4a", "flac", "wav", "opus", "vorbis", "aac", "alac")
HEIGHTS = ("best", "2160", "1440", "1080", "720", "480", "360", "240")
SPONSORBLOCK = ("off", "mark", "remove")
BROWSERS = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium", "safari")
SUB_CONVERT = ("srt", "vtt", "ass", "lrc", "none")

# Templates the user picks from, rather than typing raw yt-dlp format strings.
OUTPUT_TEMPLATES = {
    "flat":      "%(title)s [%(id)s].%(ext)s",
    "date":      "%(upload_date)s - %(title)s [%(id)s].%(ext)s",
    "channel":   "%(channel)s/%(upload_date)s - %(title)s [%(id)s].%(ext)s",
    "playlist":  "%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s",
    "archive":   "%(upload_date)s - %(title)s [%(id)s]/%(title)s.%(ext)s",
}

# Only these characters may appear in a subtitle language spec.
SUBLANG_RE = re.compile(r"^[A-Za-z0-9_.,*\-]{1,80}$")
# --download-sections, e.g. *00:01:30-00:02:45
SECTION_RE = re.compile(r"^\*\d{1,2}:\d{2}(:\d{2})?-\d{1,2}:\d{2}(:\d{2})?$")
# --dateafter / --datebefore
DATE_RE = re.compile(r"^(now-\d{1,4}(day|days|week|weeks|month|months|year|years)"
                     r"|\d{8}|today|yesterday)$")
# --playlist-items, e.g. 1-10,15,20-25
ITEMS_RE = re.compile(r"^[\d,\-: ]{1,60}$")
# --limit-rate, e.g. 2M, 500K
RATE_RE = re.compile(r"^\d{1,6}[KMG]?$", re.IGNORECASE)

# --match-filter. Only comparisons on known metadata fields are permitted.
FILTER_FIELDS = ("duration", "view_count", "like_count", "comment_count",
                 "width", "height", "fps", "filesize", "filesize_approx",
                 "playlist_index", "age_limit", "title", "description",
                 "uploader", "channel", "upload_date")
FILTER_TOKEN = re.compile(
    r"^\s*(?P<field>[a-z_]+)\s*(?P<op>[!<>=]=|[<>]|\s*[!*^$~]?=\s*)\s*(?P<val>[^&|]+?)\s*$")


class OptionError(ValueError):
    pass


def _pick(value, allowed, label, default=None):
    if value in (None, ""):
        if default is not None:
            return default
        raise OptionError(f"{label} is required")
    if value not in allowed:
        raise OptionError(f"{label} must be one of: {', '.join(allowed)}")
    return value


def validate_match_filter(text):
    """Accept only `field OP value` clauses joined by & or |."""
    if not text:
        return None
    if len(text) > 200:
        raise OptionError("filter is too long")
    for clause in re.split(r"[&|]", text):
        if not clause.strip():
            raise OptionError("filter has an empty clause")
        m = FILTER_TOKEN.match(clause)
        if not m:
            raise OptionError(f"cannot understand filter clause: {clause.strip()!r}")
        if m.group("field") not in FILTER_FIELDS:
            raise OptionError(
                f"unknown filter field {m.group('field')!r}. Allowed: "
                + ", ".join(FILTER_FIELDS))
    return text


def safe_outdir(path):
    """Resolve the output directory and refuse to escape the project folder
    unless an absolute path was given deliberately."""
    path = (path or DEFAULT_OUTDIR).strip() or DEFAULT_OUTDIR
    if os.path.isabs(path):
        full = os.path.abspath(path)
    else:
        if ".." in path.replace("\\", "/").split("/"):
            raise OptionError("output folder may not contain '..'")
        full = os.path.abspath(os.path.join(HERE, path))
    return full


URL_RE = re.compile(r"^https?://[^\s]{5,500}$", re.IGNORECASE)


def clean_urls(urls):
    if isinstance(urls, str):
        urls = [u for u in re.split(r"[\r\n]+", urls)]
    out = []
    for u in urls or []:
        u = (u or "").strip()
        if not u:
            continue
        if not URL_RE.match(u):
            raise OptionError(f"not a valid http(s) URL: {u[:60]!r}")
        out.append(u)
    if not out:
        raise OptionError("give at least one URL")
    if len(out) > 200:
        raise OptionError("too many URLs at once (limit 200)")
    return out


# ==========================================================================
# COMMAND BUILDER  (pure - covered by --self-test)
# ==========================================================================


def js_runtime_args():
    """yt-dlp only enables deno by default. If Node is present, use it -
    without a JS runtime some higher-quality formats are not offered."""
    if shutil.which("deno"):
        return []
    if shutil.which("node"):
        return ["--js-runtimes", "node"]
    return []


def build_command(opts, exe=None):
    """Turn a validated options dict into a yt-dlp argument list."""
    mode = _pick(opts.get("mode"), MODES, "mode", "video")
    urls = clean_urls(opts.get("urls"))
    outdir = safe_outdir(opts.get("output_dir"))

    exe_p = ytdlp.exe_path(exe)
    if not exe_p:
        raise OptionError("yt-dlp.exe not found next to these scripts")

    cmd = [exe_p, "--newline", "--no-warnings", "--ignore-errors", "--no-update"]
    cmd += js_runtime_args()

    # Progress in a shape we can parse reliably.
    cmd += ["--progress-template",
            "download:" + PROGRESS_MARK +
            "%(progress._percent_str)s|%(progress._speed_str)s|"
            "%(progress._eta_str)s|%(info.id)s|%(info.title).70s"]

    # ---- output layout ----
    tmpl_key = _pick(opts.get("template"), tuple(OUTPUT_TEMPLATES), "template", "date")
    cmd += ["-P", outdir, "-o", OUTPUT_TEMPLATES[tmpl_key]]

    if opts.get("archive", True):
        cmd += ["--download-archive", os.path.join(outdir, ARCHIVE_NAME)]
    if opts.get("continue_partial", True):
        cmd += ["--continue"]

    # ---- what to fetch ----
    if mode == "video":
        height = _pick(opts.get("quality"), HEIGHTS, "quality", "best")
        if height == "best":
            fmt = "bv*+ba/b"
        else:
            fmt = (f"bv*[height<={height}]+ba/b[height<={height}]/"
                   f"bv*+ba/b")
        container = _pick(opts.get("container"), CONTAINERS, "container", "mp4")
        cmd += ["-f", fmt, "--merge-output-format", container]
        if opts.get("embed_subs"):
            cmd += ["--embed-subs"]
        if opts.get("embed_thumbnail"):
            cmd += ["--embed-thumbnail"]
        if opts.get("embed_metadata", True):
            cmd += ["--embed-metadata"]
        if opts.get("embed_chapters"):
            cmd += ["--embed-chapters"]

    elif mode == "audio":
        af = _pick(opts.get("audio_format"), AUDIO_FORMATS, "audio format", "mp3")
        cmd += ["-x", "--audio-format", af, "--audio-quality",
                str(opts.get("audio_quality", "0"))]
        if opts.get("embed_thumbnail", True):
            cmd += ["--embed-thumbnail"]
        if opts.get("embed_metadata", True):
            cmd += ["--embed-metadata"]

    else:
        # metadata / subtitles / thumbnails never fetch the media stream.
        cmd += ["--skip-download"]

    # ---- side files (available in every mode) ----
    if mode in ("metadata",) or opts.get("info_json"):
        cmd += ["--write-info-json"]
    if mode in ("metadata",) or opts.get("write_description"):
        cmd += ["--write-description"]
    if opts.get("write_comments"):
        cmd += ["--write-comments"]
    if mode in ("thumbnails",) or opts.get("thumbnail"):
        cmd += ["--write-thumbnail", "--convert-thumbnails", "jpg"]

    want_subs = mode == "subtitles" or opts.get("subs") or opts.get("auto_subs")
    if want_subs:
        if mode == "subtitles" or opts.get("subs"):
            cmd += ["--write-subs"]
        if mode == "subtitles" or opts.get("auto_subs"):
            cmd += ["--write-auto-subs"]
        langs = (opts.get("sub_langs") or "en.*").strip()
        if not SUBLANG_RE.match(langs):
            raise OptionError("subtitle languages may only contain letters, "
                              "digits, dots, commas, hyphens and *")
        cmd += ["--sub-langs", langs]
        conv = _pick(opts.get("convert_subs"), SUB_CONVERT, "subtitle format", "srt")
        if conv != "none":
            cmd += ["--convert-subs", conv]

    # ---- trimming / SponsorBlock ----
    section = (opts.get("section") or "").strip()
    if section:
        if not SECTION_RE.match(section):
            raise OptionError("section must look like *00:01:30-00:02:45")
        cmd += ["--download-sections", section]

    sb = _pick(opts.get("sponsorblock"), SPONSORBLOCK, "sponsorblock", "off")
    if sb == "mark":
        cmd += ["--sponsorblock-mark", "all"]
    elif sb == "remove":
        cmd += ["--sponsorblock-remove", "sponsor,selfpromo"]

    # ---- filtering ----
    mf = validate_match_filter((opts.get("match_filter") or "").strip())
    if mf:
        cmd += ["--match-filter", mf]

    for key, flag in (("date_after", "--dateafter"), ("date_before", "--datebefore")):
        val = (opts.get(key) or "").strip()
        if val:
            if not DATE_RE.match(val):
                raise OptionError(f"{flag} must be YYYYMMDD, today, yesterday "
                                  f"or now-7days style")
            cmd += [flag, val]

    items = (opts.get("playlist_items") or "").strip()
    if items:
        if not ITEMS_RE.match(items):
            raise OptionError("playlist items may only contain digits, commas and hyphens")
        cmd += ["--playlist-items", items]

    rate = (opts.get("limit_rate") or "").strip()
    if rate:
        if not RATE_RE.match(rate):
            raise OptionError("speed limit must look like 2M or 500K")
        cmd += ["--limit-rate", rate]

    # ---- misc ----
    if opts.get("live_from_start"):
        cmd += ["--live-from-start"]
    browser = opts.get("cookies_browser")
    if browser:
        _pick(browser, BROWSERS, "browser")
        cmd += ["--cookies-from-browser", browser]

    cmd += ["--"] + urls
    return cmd, outdir


def describe(cmd):
    """Render the command the way the user would type it, for display."""
    out = []
    for part in cmd:
        out.append(f'"{part}"' if (" " in part or "|" in part) else part)
    return " ".join(out)


# ==========================================================================
# PRESETS
# ==========================================================================

PRESETS = {
    "channel-backup": {
        "label": "Full channel backup",
        "hint": "Video + thumbnail + description + metadata + captions, never twice.",
        "opts": {"mode": "video", "quality": "best", "container": "mp4",
                 "thumbnail": True, "write_description": True, "info_json": True,
                 "subs": True, "auto_subs": True, "sub_langs": "en.*",
                 "convert_subs": "srt", "embed_metadata": True,
                 "template": "date", "archive": True},
    },
    "video-1080": {
        "label": "Video, 1080p MP4",
        "hint": "Single videos or a playlist, merged to MP4.",
        "opts": {"mode": "video", "quality": "1080", "container": "mp4",
                 "embed_metadata": True, "embed_thumbnail": True,
                 "template": "date", "archive": True},
    },
    "audio-mp3": {
        "label": "Audio only, MP3",
        "hint": "Best-quality MP3 with cover art and tags. Good for your beats.",
        "opts": {"mode": "audio", "audio_format": "mp3", "audio_quality": "0",
                 "embed_thumbnail": True, "embed_metadata": True,
                 "template": "date", "archive": True},
    },
    "audio-wav": {
        "label": "Audio only, WAV",
        "hint": "Uncompressed, for re-editing in a DAW.",
        "opts": {"mode": "audio", "audio_format": "wav",
                 "embed_metadata": False, "embed_thumbnail": False,
                 "template": "date", "archive": True},
    },
    "metadata-only": {
        "label": "Metadata only",
        "hint": "Info JSON, description and thumbnail. No media, very fast.",
        "opts": {"mode": "metadata", "thumbnail": True, "template": "flat",
                 "archive": False},
    },
    "subtitles-only": {
        "label": "Captions only",
        "hint": "Subtitles and auto-captions as SRT. No media.",
        "opts": {"mode": "subtitles", "sub_langs": "en.*",
                 "convert_subs": "srt", "template": "flat", "archive": False},
    },
    "thumbnails-only": {
        "label": "Thumbnails only",
        "hint": "Every thumbnail as a JPG.",
        "opts": {"mode": "thumbnails", "template": "flat", "archive": False},
    },
    "recent-week": {
        "label": "New uploads, last 7 days",
        "hint": "Point at a channel and run it on a schedule.",
        "opts": {"mode": "video", "quality": "1080", "container": "mp4",
                 "date_after": "now-7days", "thumbnail": True,
                 "template": "date", "archive": True},
    },
}


# ==========================================================================
# RUNNING
# ==========================================================================

PROG_RE = re.compile(re.escape(PROGRESS_MARK) + r"(.*)")
ITEM_RE = re.compile(r"Downloading item (\d+) of (\d+)")
DEST_RE = re.compile(r"\[download\] Destination: (.+)")
DONE_RE = re.compile(r"\[download\] (.+) has already been recorded")


def run(cmd, on_log=None, on_progress=None, should_stop=None):
    """Stream yt-dlp, separating progress lines from ordinary log lines."""
    log = on_log or (lambda m: None)
    state = {"item": 0, "items": 0, "files": 0}

    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            bufsize=1, **kwargs)
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue

            m = PROG_RE.search(line)
            if m:
                bits = m.group(1).split("|")
                while len(bits) < 5:
                    bits.append("")
                pct, speed, eta, vid, title = (b.strip() for b in bits[:5])
                if on_progress:
                    on_progress({"percent": pct, "speed": speed, "eta": eta,
                                 "video_id": vid, "title": title,
                                 "item": state["item"], "items": state["items"]})
                continue

            mi = ITEM_RE.search(line)
            if mi:
                state["item"], state["items"] = int(mi.group(1)), int(mi.group(2))
            if DEST_RE.search(line):
                state["files"] += 1
            log(line)

            if should_stop and should_stop():
                proc.terminate()
                log("Stopped by request.")
                break
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        code = proc.wait()

    state["exit_code"] = code
    return state


def list_formats(url, exe=None, cookies_browser=None):
    """`yt-dlp -F` as plain text, for the format table in the UI."""
    urls = clean_urls([url])
    exe_p = ytdlp.exe_path(exe)
    if not exe_p:
        raise OptionError("yt-dlp.exe not found")
    cmd = [exe_p, "-F", "--no-warnings", "--no-update"] + js_runtime_args()
    if cookies_browser:
        _pick(cookies_browser, BROWSERS, "browser")
        cmd += ["--cookies-from-browser", cookies_browser]
    cmd += ["--"] + urls
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=180, **kwargs)
    return (out.stdout or "") + (out.stderr or "")


# ==========================================================================
# ENVIRONMENT
# ==========================================================================


def environment():
    ff = shutil.which("ffmpeg")
    ffv = None
    if ff:
        try:
            r = subprocess.run([ff, "-version"], capture_output=True, text=True,
                               timeout=20, encoding="utf-8", errors="replace")
            ffv = (r.stdout or "").split("\n")[0][:90]
        except Exception:
            pass
    runtime = "deno" if shutil.which("deno") else ("node" if shutil.which("node") else None)
    return {
        "ytdlp_version": ytdlp.version(),
        "ytdlp_path": ytdlp.exe_path(),
        "ffmpeg": bool(ff),
        "ffmpeg_version": ffv,
        "js_runtime": runtime,
        "default_outdir": safe_outdir(DEFAULT_OUTDIR),
    }


# ==========================================================================
# SELF TEST
# ==========================================================================


def self_test():
    print("Running download self-test (no network, nothing downloaded)...\n")
    fails = 0

    def ok(name, cond, extra=""):
        nonlocal fails
        print(("  ok   " if cond else "  FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
        if not cond:
            fails += 1

    def rejects(name, opts):
        try:
            build_command(opts)
            ok(name, False, "was accepted")
        except OptionError:
            ok(name, True)

    base = {"urls": ["https://www.youtube.com/watch?v=abc"]}

    cmd, out = build_command({**base, "mode": "video", "quality": "1080"})
    ok("video build", "-f" in cmd and "--merge-output-format" in cmd)
    ok("1080 cap in format string", any("height<=1080" in c for c in cmd))
    ok("archive on by default", "--download-archive" in cmd)
    ok("url is last and after --", cmd[-1] == base["urls"][0] and "--" in cmd)
    ok("output dir applied", "-P" in cmd)

    cmd, _ = build_command({**base, "mode": "video", "quality": "best"})
    ok("best quality uses bv*+ba/b", "bv*+ba/b" in cmd)

    cmd, _ = build_command({**base, "mode": "audio", "audio_format": "mp3"})
    ok("audio uses -x", "-x" in cmd and "mp3" in cmd)
    ok("audio embeds thumbnail by default", "--embed-thumbnail" in cmd)
    ok("audio does not merge video", "--merge-output-format" not in cmd)

    cmd, _ = build_command({**base, "mode": "metadata"})
    ok("metadata skips download", "--skip-download" in cmd)
    ok("metadata writes info json", "--write-info-json" in cmd)
    ok("metadata writes description", "--write-description" in cmd)

    cmd, _ = build_command({**base, "mode": "subtitles"})
    ok("subtitles skip download", "--skip-download" in cmd)
    ok("subtitles auto + manual", "--write-subs" in cmd and "--write-auto-subs" in cmd)
    ok("subtitles converted to srt", "srt" in cmd)

    cmd, _ = build_command({**base, "mode": "thumbnails"})
    ok("thumbnails convert to jpg", "--convert-thumbnails" in cmd)

    cmd, _ = build_command({**base, "sponsorblock": "remove"})
    ok("sponsorblock remove", "--sponsorblock-remove" in cmd)
    cmd, _ = build_command({**base, "sponsorblock": "mark"})
    ok("sponsorblock mark", "--sponsorblock-mark" in cmd)

    cmd, _ = build_command({**base, "section": "*00:01:30-00:02:45"})
    ok("valid section accepted", "--download-sections" in cmd)
    rejects("bad section rejected", {**base, "section": "; rm -rf /"})

    cmd, _ = build_command({**base, "match_filter": "duration < 600 & view_count >= 10000"})
    ok("valid filter accepted", "--match-filter" in cmd)
    rejects("unknown filter field rejected", {**base, "match_filter": "evil < 1"})
    rejects("filter garbage rejected", {**base, "match_filter": "--exec rm"})

    cmd, _ = build_command({**base, "date_after": "now-7days"})
    ok("relative date accepted", "--dateafter" in cmd)
    rejects("bad date rejected", {**base, "date_after": "--exec evil"})

    cmd, _ = build_command({**base, "playlist_items": "1-10,15"})
    ok("playlist items accepted", "--playlist-items" in cmd)
    rejects("bad playlist items rejected", {**base, "playlist_items": "1;evil"})

    cmd, _ = build_command({**base, "limit_rate": "2M"})
    ok("rate limit accepted", "--limit-rate" in cmd)
    rejects("bad rate rejected", {**base, "limit_rate": "fast"})

    cmd, _ = build_command({**base, "cookies_browser": "chrome"})
    ok("cookies accepted", "--cookies-from-browser" in cmd)
    rejects("unknown browser rejected", {**base, "cookies_browser": "evilbrowser"})

    rejects("bad url rejected", {"urls": ["file:///etc/passwd"]})
    rejects("empty url list rejected", {"urls": []})
    rejects("unknown mode rejected", {**base, "mode": "wat"})
    rejects("unknown container rejected", {**base, "container": "avi"})
    rejects("unknown audio format rejected", {**base, "mode": "audio", "audio_format": "wma"})
    rejects("directory traversal rejected", {**base, "output_dir": "../../windows"})
    rejects("bad sub langs rejected", {**base, "mode": "subtitles", "sub_langs": "en; evil"})

    # An option value must never be able to become a separate flag.
    cmd, _ = build_command({**base, "sub_langs": "en.*,tl.*", "mode": "subtitles"})
    ok("sub langs stay one argument", "en.*,tl.*" in cmd)

    # Presets must all build.
    for key, p in PRESETS.items():
        try:
            build_command({**p["opts"], **base})
            ok(f"preset builds: {key}", True)
        except OptionError as e:
            ok(f"preset builds: {key}", False, str(e))

    print()
    if fails:
        print(f"SELF-TEST FAILED: {fails} case(s).")
        return 1
    print("SELF-TEST PASSED.")
    return 0


def cli():
    ap = argparse.ArgumentParser(description="yt-dlp download / archive engine.")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--env", action="store_true", help="Show tool versions.")
    ap.add_argument("--formats", metavar="URL", help="List available formats.")
    ap.add_argument("--preset", choices=sorted(PRESETS))
    ap.add_argument("--url", action="append", help="URL (repeatable).")
    ap.add_argument("--output-dir", default=DEFAULT_OUTDIR)
    ap.add_argument("--dry-run", action="store_true", help="Print the command only.")
    a = ap.parse_args()

    if a.self_test:
        sys.exit(self_test())
    if a.env:
        for k, v in environment().items():
            print(f"  {k:16}: {v}")
        return
    if a.formats:
        print(list_formats(a.formats))
        return
    if a.preset:
        if not a.url:
            print("Give at least one --url"); sys.exit(1)
        opts = {**PRESETS[a.preset]["opts"], "urls": a.url, "output_dir": a.output_dir}
        cmd, outdir = build_command(opts)
        print(describe(cmd), "\n")
        if a.dry_run:
            return
        os.makedirs(outdir, exist_ok=True)
        st = run(cmd, on_log=print,
                 on_progress=lambda p: print(f"  {p['percent']} {p['speed']} "
                                             f"eta {p['eta']}  {p['title'][:50]}",
                                             end="\r", flush=True))
        print(f"\nexit code {st['exit_code']}, {st['files']} file(s) started")
        return
    ap.print_help()


if __name__ == "__main__":
    cli()
