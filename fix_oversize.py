#!/usr/bin/env python3
"""
Fixes the videos that main.py has to skip because replacing the Instagram
handle would push the description past YouTube's 5000-character limit.

`prod.crmdrm` is 4 characters longer than `crm.drm`, so a description already
sitting at the ceiling no longer fits after the swap.

This script makes room using WHITESPACE-ONLY edits, applied in order of how
visible they are, stopping the moment the description fits:

    1. remove trailing spaces/tabs at the end of each line   (invisible)
    2. remove blank space at the very end of the description (invisible)
    3. collapse runs of 4+ blank lines down to 3             (barely visible)
    4. collapse runs of 3+ blank lines down to 2             (slightly visible)
    5. collapse runs of 2+ blank lines down to 1             (visible)

No word, link, tag, e-mail or piece of punctuation is ever touched. If a
description still does not fit after step 5, the script leaves it alone and
tells you to edit it by hand.

Default mode is a dry run. Nothing is written until you type UPDATE.

    python fix_oversize.py              # preview only
    python fix_oversize.py --apply      # preview, then offer to write
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

import main

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

LIMIT = 5000
OVERSIZE_BACKUP = "oversize_backup.json"


# ==========================================================================
# LENGTH
# ==========================================================================


def utf16_len(s):
    """Length in UTF-16 code units - how many platforms count 'characters'.
    An emoji counts as 2 here but 1 as a Python code point."""
    return len(s.encode("utf-16-le")) // 2


def measured_len(s):
    """Conservative length: whichever counting method gives the bigger number.
    Evidence from this channel: YouTube accepted a description of 4998 code
    points / 5000 UTF-16 units, and nothing longer by either measure."""
    return max(len(s), utf16_len(s))


def fits(s):
    return measured_len(s) <= LIMIT


# ==========================================================================
# WHITESPACE REDUCTION LADDER
# ==========================================================================


def strip_line_ends(text):
    """Remove trailing spaces and tabs from the end of every line."""
    return re.sub(r"[ \t]+(?=\n|$)", "", text)


def strip_document_end(text):
    """Remove blank space at the very end of the description."""
    return text.rstrip()


def collapse_blanks(text, keep):
    """Collapse runs of blank lines so that at most `keep` blank lines remain
    (i.e. at most keep+1 consecutive newlines)."""
    return re.sub(r"\n{%d,}" % (keep + 2), "\n" * (keep + 1), text)


STEPS = [
    ("trailing spaces at line ends", strip_line_ends, "invisible"),
    ("blank space at end of description", strip_document_end, "invisible"),
    ("runs of 4+ blank lines -> 3", lambda t: collapse_blanks(t, 3), "barely visible"),
    ("runs of 3+ blank lines -> 2", lambda t: collapse_blanks(t, 2), "slightly visible"),
    ("runs of 2+ blank lines -> 1", lambda t: collapse_blanks(t, 1), "visible"),
]


def shrink(text):
    """Apply the ladder until the text fits. Returns (result, steps_applied,
    fitted_bool). Steps that save nothing are not reported."""
    applied = []
    cur = text
    if fits(cur):
        return cur, applied, True
    for label, fn, visibility in STEPS:
        before = measured_len(cur)
        cur = fn(cur)
        saved = before - measured_len(cur)
        if saved:
            applied.append({"label": label, "saved": saved, "visibility": visibility})
        if fits(cur):
            return cur, applied, True
    return cur, applied, fits(cur)


# ==========================================================================
# SELF TEST
# ==========================================================================


def self_test():
    print("Running fix_oversize self-test (no network)...\n")
    fails = 0

    def check(name, got, want):
        nonlocal fails
        ok = got == want
        if not ok:
            fails += 1
            print(f"  FAIL {name}\n       got  {got!r}\n       want {want!r}")
        else:
            print(f"  ok   {name}")

    check("strip line ends", strip_line_ends("a   \nb\t\nc"), "a\nb\nc")
    check("strip doc end", strip_document_end("a\n\n\n   "), "a")
    check("collapse to 1 blank", collapse_blanks("a\n\n\n\nb", 1), "a\n\nb")
    check("collapse to 2 blanks", collapse_blanks("a\n\n\n\n\nb", 2), "a\n\n\nb")
    check("collapse leaves single newline", collapse_blanks("a\nb", 1), "a\nb")
    check("utf16 counts emoji as 2", utf16_len("a\U0001f525"), 3)
    check("codepoints count emoji as 1", len("a\U0001f525"), 2)
    check("measured_len is the max", measured_len("a\U0001f525"), 3)

    # No visible character may ever be lost.
    sample = ("Buy this beat 🛒   \n\n\n\n\nInstagram: @prod.crmdrm   \n"
              "Email: business.crmdrm@gmail.com\n\n\n   ")
    out, steps, ok = shrink(sample + "x" * 5000)
    visible_in = re.sub(r"\s+", "", sample)
    visible_out = re.sub(r"\s+", "", out)[:len(visible_in)]
    check("no visible characters lost", visible_out, visible_in)

    # A description that already fits is returned untouched.
    small = "short description"
    check("untouched when it already fits", shrink(small)[0], small)

    print()
    if fails:
        print(f"SELF-TEST FAILED: {fails} case(s).")
        return 1
    print("SELF-TEST PASSED.")
    return 0


# ==========================================================================
# REPORTING
# ==========================================================================


def show_tail(text, n=3):
    """Render the last few lines with whitespace made visible."""
    lines = text.split("\n")[-n:]
    out = []
    for ln in lines:
        vis = ln.replace("\t", "\\t")
        vis = re.sub(r" +$", lambda m: "·" * len(m.group(0)), vis)
        out.append(vis if vis.strip() else ("<blank>" if not vis else vis))
    return out


def report(rec):
    o, n = rec["original"], rec["shrunk"]
    print("-" * 78)
    print(f"  {rec['title'][:70]}")
    print(f"  https://studio.youtube.com/video/{rec['video_id']}/edit  ({rec['privacy']})")
    print(f"  after handle swap : {rec['swapped_len']} chars  "
          f"(over the limit by {rec['swapped_len'] - LIMIT})")
    if rec["fitted"]:
        print(f"  after whitespace  : {measured_len(n)} chars  -> FITS")
        for s in rec["steps"]:
            print(f"      - removed {s['label']}: saved {s['saved']} ({s['visibility']})")
    else:
        print(f"  after whitespace  : {measured_len(n)} chars  -> STILL TOO LONG, "
              f"needs {measured_len(n) - LIMIT} more removed by hand")
    print(f"  visible text unchanged: {rec['visible_same']}")
    print("  end of description, before -> after (· = trailing space):")
    for ln in show_tail(rec["swapped"]):
        print(f"      | {ln}")
    print("      ---")
    for ln in show_tail(n):
        print(f"      | {ln}")


# ==========================================================================
# MAIN
# ==========================================================================


def main_cli():
    ap = argparse.ArgumentParser(
        description="Fit over-long descriptions by trimming whitespace only.")
    ap.add_argument("--apply", action="store_true",
                    help="Offer to write the changes after showing the preview.")
    ap.add_argument("--self-test", action="store_true",
                    help="Run the whitespace tests only. No network.")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())

    if self_test() != 0 or main.run_self_test(verbose=False) != 0:
        print("Refusing to continue with failing tests.")
        sys.exit(1)
    print()

    progress = main.load_progress()
    quota = main.QuotaTracker(progress)
    print(quota.summary())

    youtube = main.build_service()
    print("Looking up your channel...")
    channel = main.get_channel(youtube, quota)
    print(f"  Channel: {channel['title']}  ({channel['id']})")
    print("Listing uploads...")
    ids = main.list_upload_video_ids(youtube, quota, channel["uploads_playlist"])
    print("Reading descriptions...")
    videos = main.fetch_videos(youtube, quota, ids)
    main.save_progress(progress)

    # Find the ones main.py has to skip.
    records = []
    for v in videos:
        vid = v["id"]
        if vid in progress["completed"]:
            continue
        original = v["snippet"].get("description", "") or ""
        swapped, hits = main.apply_replacements(original)
        if swapped == original:
            continue                      # nothing to replace
        if fits(swapped):
            continue                      # main.py can handle this one
        shrunk, steps, fitted = shrink(swapped)
        records.append({
            "video": v,
            "video_id": vid,
            "title": v["snippet"].get("title", ""),
            "privacy": v.get("status", {}).get("privacyStatus", "unknown"),
            "original": original,
            "swapped": swapped,
            "swapped_len": measured_len(swapped),
            "shrunk": shrunk,
            "steps": steps,
            "fitted": fitted,
            "visible_same": re.sub(r"\s+", "", shrunk) == re.sub(r"\s+", "", swapped),
        })

    print()
    print("=" * 78)
    print("OVER-LENGTH DESCRIPTIONS - DRY RUN, nothing has been modified")
    print("=" * 78)

    if not records:
        print("No over-length videos left. Nothing to do.")
        return

    for rec in records:
        report(rec)

    fixable = [r for r in records if r["fitted"] and r["visible_same"]]
    manual = [r for r in records if r not in fixable]

    print("=" * 78)
    print(f"Over-length videos found        : {len(records)}")
    print(f"Fixable by trimming whitespace  : {len(fixable)}")
    print(f"Still need manual editing       : {len(manual)}")
    for r in manual:
        print(f"    https://studio.youtube.com/video/{r['video_id']}/edit  "
              f"needs {measured_len(r['shrunk']) - LIMIT} more chars removed")
    only_invisible = all(s["visibility"] == "invisible"
                         for r in fixable for s in r["steps"])
    print(f"All edits invisible on YouTube  : {only_invisible}")
    cost = len(fixable) * main.QUOTA_COST["videos.update"]
    print(f"Quota needed                    : {cost} units "
          f"(budget left today: {quota.remaining()})")
    print("=" * 78)
    print()

    if not args.apply:
        print("Dry run only. Re-run with --apply to write these changes.")
        return
    if not fixable:
        print("Nothing can be fixed automatically.")
        return
    if not sys.stdin.isatty():
        print("Not an interactive terminal. Nothing was modified.")
        return
    if cost > quota.remaining():
        print("Not enough quota left today. Try again after the reset.")
        return

    print("!" * 78)
    print(f"You are about to modify {len(fixable)} video descriptions on "
          f"{channel['title']}.")
    print("Each change is: the Instagram handle swap, plus whitespace removal.")
    print("No visible text is altered.")
    print("!" * 78)
    if input("Type exactly  UPDATE  to proceed: ") != "UPDATE":
        print("Cancelled. Nothing was modified.")
        return

    # Dedicated backup for these, since main.py's backup does not cover them.
    payload = {
        "created_at": main.now_iso(),
        "channel_id": channel["id"],
        "note": "over-length descriptions fixed by fix_oversize.py",
        "video_count": len(fixable),
        "videos": [{"video_id": r["video_id"], "title": r["title"],
                    "original_description": r["original"],
                    "new_description": r["shrunk"]} for r in fixable],
    }
    try:
        main.atomic_write_json(OVERSIZE_BACKUP, payload)
        check = json.load(open(OVERSIZE_BACKUP, encoding="utf-8"))
        for saved, r in zip(check["videos"], fixable):
            if saved["original_description"] != r["original"]:
                raise ValueError(f"backup mismatch for {r['video_id']}")
        print(f"Backup written and verified: {OVERSIZE_BACKUP} "
              f"({os.path.getsize(OVERSIZE_BACKUP):,} bytes)")
    except Exception as exc:
        print(f"ERROR: backup failed ({exc}). CANCELLED - nothing was changed.")
        sys.exit(1)

    print()
    updated = failed = 0
    for i, r in enumerate(fixable, 1):
        if not quota.can_afford("videos.update"):
            print(f"[{i}/{len(fixable)}] Stopping: quota budget exhausted.")
            break
        try:
            main.update_description(youtube, quota, r["video"], r["shrunk"])
        except main.QuotaExceeded:
            print(f"[{i}/{len(fixable)}] Stopping: daily quota exhausted.")
            main.save_progress(progress)
            break
        except Exception as exc:
            failed += 1
            progress["failed"][r["video_id"]] = {
                "title": r["title"], "error": str(exc), "at": main.now_iso()}
            main.save_progress(progress)
            print(f"[{i}/{len(fixable)}] FAILED: {r['title'][:55]}")
            print(f"          {exc}")
            continue
        updated += 1
        progress["completed"][r["video_id"]] = {
            "title": r["title"], "updated_at": main.now_iso(),
            "note": "whitespace trimmed to fit 5000-char limit"}
        progress["failed"].pop(r["video_id"], None)
        main.save_progress(progress)
        print(f"[{i}/{len(fixable)}] Updated: {r['title'][:55]}")

    main.save_progress(progress)
    print()
    print("=" * 78)
    print(f"Updated: {updated}   Failed: {failed}")
    print(main.QuotaTracker(progress).summary())
    if manual:
        print(f"{len(manual)} video(s) still need manual editing - see the list above.")
    print("=" * 78)


if __name__ == "__main__":
    main_cli()
