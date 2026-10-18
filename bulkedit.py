#!/usr/bin/env python3
"""
Generalised, safe bulk editing of YouTube descriptions.

main.py does one hard-coded job: swap an old Instagram handle. This module
generalises that to any set of rules you define, while keeping every safety
property that made the Instagram job survivable:

  * a rule only ever edits the parts of a description it matches
  * nothing is written until you have seen a dry run
  * a verified backup is written before the first change
  * progress is checkpointed after every single video

Rules live in rules.json and look like this:

  {
    "name": "Update BeatStars link",
    "enabled": true,
    "type": "text",            # or "regex"
    "find": "beatstars.com/crmdrm",
    "replace": "beatstars.com/crmdrmbeats",
    "case_sensitive": false,
    "word_boundary": true,     # text rules only
    "protect": ["business.crmdrm@gmail.com"]
  }

`protect` is the important one: any string listed there must appear the same
number of times before and after the edit, or the rule is rejected for that
video. It is how you stop a careless rule from eating your e-mail address.

Standalone use:

    python bulkedit.py --list                 # show configured rules
    python bulkedit.py --test                 # run rules against sample text
    python bulkedit.py --check                # validate rules, no network
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

RULES_FILE = "rules.json"
MAX_DESCRIPTION = 5000

# A rule that rewrites most of a description is almost certainly a mistake.
MAX_CHANGE_RATIO = 0.35


# ==========================================================================
# LENGTH (shared with fix_oversize.py's reasoning)
# ==========================================================================


def utf16_len(s):
    return len(s.encode("utf-16-le")) // 2


def measured_len(s):
    """Conservative character count: whichever measure is larger. An emoji is
    1 Python code point but 2 UTF-16 units, and YouTube counts the stricter."""
    return max(len(s), utf16_len(s))


# ==========================================================================
# RULE MODEL
# ==========================================================================

DEFAULT_RULES = [
    {
        "name": "Instagram handle",
        "enabled": False,
        "type": "regex",
        "find": r"(?<![\w.+\-])@crm\.drm(?!\.?\w)",
        "replace": "@prod.crmdrm",
        "case_sensitive": False,
        "protect": ["business.crmdrm@gmail.com", "Prod. CRMDRM"],
        "notes": "Already completed by main.py. Kept as a worked example.",
    },
    {
        "name": "Instagram profile URL",
        "enabled": False,
        "type": "regex",
        "find": r"\b((?:https?://)?(?:[a-z0-9-]+\.)*instagram\.com/)crm\.drm(?!\.?\w)",
        "replace": r"\1prod.crmdrm",
        "case_sensitive": False,
        "protect": ["facebook.com/crmdrm.beats"],
        "notes": "Already completed by main.py. Kept as a worked example.",
    },
]


class RuleError(ValueError):
    pass


def load_rules(path=RULES_FILE):
    if not os.path.exists(path):
        save_rules(DEFAULT_RULES, path)
        return list(DEFAULT_RULES)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = data.get("rules", [])
    return data


def save_rules(rules, path=RULES_FILE):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rules, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def compile_rule(rule):
    """Validate one rule and return (pattern, replacement). Raises RuleError
    with a message aimed at a human, not a stack trace."""
    name = rule.get("name") or "(unnamed)"
    find = rule.get("find")
    if not find:
        raise RuleError(f"{name}: 'find' is empty")
    if rule.get("replace") is None:
        raise RuleError(f"{name}: 'replace' is missing")

    flags = 0 if rule.get("case_sensitive") else re.IGNORECASE

    if rule.get("type") == "regex":
        try:
            pattern = re.compile(find, flags)
        except re.error as exc:
            raise RuleError(f"{name}: invalid regex - {exc}") from exc
        replacement = rule["replace"]
        # Catch \1 style references pointing at groups that do not exist.
        for ref in re.findall(r"\\(\d+)", replacement):
            if int(ref) > pattern.groups:
                raise RuleError(
                    f"{name}: replacement uses \\{ref} but the pattern has "
                    f"only {pattern.groups} group(s)")
    else:
        escaped = re.escape(find)
        if rule.get("word_boundary"):
            escaped = r"(?<!\w)" + escaped + r"(?!\w)"
        pattern = re.compile(escaped, flags)
        # A literal replacement must not be treated as a regex template.
        replacement = rule["replace"].replace("\\", "\\\\")

    if pattern.match(""):
        raise RuleError(f"{name}: pattern matches the empty string, which would "
                        f"insert text everywhere")
    return pattern, replacement


def validate_rules(rules):
    """Returns (compiled, errors). Disabled rules are skipped but still
    checked, so a broken rule is reported before you enable it."""
    compiled, errors = [], []
    seen = Counter()
    for rule in rules:
        name = rule.get("name") or "(unnamed)"
        seen[name] += 1
        if seen[name] > 1:
            errors.append(f"{name}: duplicate rule name")
        try:
            pattern, replacement = compile_rule(rule)
        except RuleError as exc:
            errors.append(str(exc))
            continue
        if rule.get("enabled"):
            compiled.append((rule, pattern, replacement))
    return compiled, errors


# ==========================================================================
# APPLYING
# ==========================================================================


def apply_rules(text, compiled):
    """Apply every enabled rule in order.

    Returns (new_text, hits, rejections). A rejection means a rule matched but
    its result failed a safety check, so that rule was skipped for this video
    while the others still applied."""
    if not text:
        return text, [], []

    hits, rejections = [], []
    current = text

    for rule, pattern, replacement in compiled:
        matches = list(pattern.finditer(current))
        if not matches:
            continue
        candidate = pattern.sub(replacement, current)

        problem = safety_check(rule, current, candidate, len(matches))
        if problem:
            rejections.append({"rule": rule.get("name"), "reason": problem,
                               "matches": len(matches)})
            continue

        hits.append({"rule": rule.get("name"),
                     "count": len(matches),
                     "samples": [m.group(0) for m in matches[:3]]})
        current = candidate

    return current, hits, rejections


def safety_check(rule, before, after, match_count):
    """Return a human-readable reason to reject, or None to allow."""
    if after == before:
        return "rule matched but changed nothing"

    for token in rule.get("protect") or []:
        if before.count(token) != after.count(token):
            return f"would alter protected text {token!r}"

    if measured_len(after) > MAX_DESCRIPTION:
        return (f"result is {measured_len(after)} characters, over YouTube's "
                f"{MAX_DESCRIPTION} limit")

    changed = abs(len(after) - len(before))
    if len(before) and changed / len(before) > MAX_CHANGE_RATIO:
        return (f"would change {changed} characters "
                f"({changed / len(before):.0%} of the description) - "
                f"that looks like a mistake")

    # Deleting a link is almost never intended by a find/replace.
    lost = set(extract_urls(before)) - set(extract_urls(after))
    def targets_url(url):
        if rule.get("find", "").lower() in url.lower():
            return True
        if url.lower() in str(rule.get("replace", "")).lower():
            return True
        if rule.get("type") == "regex":
            try:
                flags = 0 if rule.get("case_sensitive") else re.IGNORECASE
                rewritten = re.sub(rule.get("find", ""), rule.get("replace", ""), url, flags=flags)
                return rewritten != url and bool(re.fullmatch(r"https?://[^\s]+", rewritten))
            except re.error:
                return False
        return False
    intentional = [u for u in lost if targets_url(u)]
    if lost and len(intentional) != len(lost):
        return f"would remove {len(lost)} link(s), e.g. {sorted(lost)[0][:60]}"

    return None


# ==========================================================================
# LINK EXTRACTION / CHECKING
# ==========================================================================

URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+", re.IGNORECASE)


def extract_urls(text):
    """URLs in a description, with trailing punctuation stripped."""
    out = []
    for m in URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,;:!?")
        out.append(u)
    return out


def link_report(videos):
    """videos: iterable of (video_id, title, description).
    Returns links sorted by how often they appear."""
    counts = Counter()
    where = {}
    for vid, title, desc in videos:
        for u in set(extract_urls(desc)):
            counts[u] += 1
            where.setdefault(u, []).append(vid)
    return [{"url": u, "count": c, "video_ids": where[u][:50]}
            for u, c in counts.most_common()]


def domain_of(url):
    m = re.match(r"https?://([^/]+)", url, re.IGNORECASE)
    host = m.group(1).lower() if m else ""
    return host[4:] if host.startswith("www.") else host


# ==========================================================================
# APPEND / PREPEND
# ==========================================================================


def add_block(text, block, where="end", skip_if_present=True):
    """Append or prepend a block of text, refusing to duplicate it and
    refusing to overflow the character limit."""
    block = block.rstrip("\n")
    if not block:
        return text, "block is empty"
    if skip_if_present and block.strip() in (text or ""):
        return text, "already present"
    joined = (text.rstrip() + "\n\n" + block) if where == "end" \
        else (block + "\n\n" + (text or "").lstrip())
    if measured_len(joined) > MAX_DESCRIPTION:
        return text, (f"would be {measured_len(joined)} characters, over the "
                      f"{MAX_DESCRIPTION} limit")
    return joined, None


# ==========================================================================
# PREVIEW HELPERS
# ==========================================================================


def diff_snippets(before, after, compiled, width=70):
    """BEFORE/AFTER excerpts around each match, for the UI."""
    out = []
    for rule, pattern, _repl in compiled:
        for m in pattern.finditer(before):
            s = max(0, m.start() - width)
            e = min(len(before), m.end() + width)
            frag = before[s:e]
            frag_after, _h, _r = apply_rules(frag, [(rule, pattern, _repl)])
            out.append({
                "rule": rule.get("name"),
                "before": _flat(frag, s > 0, e < len(before)),
                "after": _flat(frag_after, s > 0, e < len(before)),
            })
            if len(out) >= 6:
                return out
    return out


def _flat(s, lead, trail):
    s = s.replace("\r", " ").replace("\n", " \\n ")
    s = re.sub(r"\s{2,}", " ", s).strip()
    return ("..." if lead else "") + s + ("..." if trail else "")


# ==========================================================================
# SELF TEST
# ==========================================================================

SAMPLE = ("(free for profit) indie type beat\n\n"
          "produced by CRMDRM\n"
          "Instagram: @prod.crmdrm\n"
          "Email: business.crmdrm@gmail.com\n"
          "https://www.beatstars.com/crmdrm\n"
          "https://www.facebook.com/crmdrm.beats\n"
          "https://soundcloud.com/prod-crmdrm 🔥\n")


def self_test():
    print("Running bulkedit self-test (no network)...\n")
    fails = 0

    def check(name, cond):
        nonlocal fails
        print(("  ok   " if cond else "  FAIL ") + name)
        if not cond:
            fails += 1

    # text rule
    r = {"name": "t", "enabled": True, "type": "text",
         "find": "beatstars.com/crmdrm", "replace": "beatstars.com/crmdrmbeats"}
    c, errs = validate_rules([r])
    check("text rule compiles", not errs)
    out, hits, rej = apply_rules(SAMPLE, c)
    check("text rule replaced once", hits and hits[0]["count"] == 1)
    check("email untouched", "business.crmdrm@gmail.com" in out)
    check("emoji survived", "🔥" in out)

    # protect guard
    bad = {"name": "b", "enabled": True, "type": "text",
           "find": "crmdrm", "replace": "XX",
           "protect": ["business.crmdrm@gmail.com"]}
    c2, _ = validate_rules([bad])
    out2, hits2, rej2 = apply_rules(SAMPLE, c2)
    check("protected text blocks the rule", bool(rej2) and out2 == SAMPLE)

    # link-removal guard
    killer = {"name": "k", "enabled": True, "type": "regex",
              "find": r"https?://\S+", "replace": ""}
    c3, _ = validate_rules([killer])
    out3, _h, rej3 = apply_rules(SAMPLE, c3)
    check("link-deleting rule rejected", bool(rej3) and out3 == SAMPLE)

    # invalid regex
    _c, errs2 = validate_rules([{"name": "x", "enabled": True,
                                 "type": "regex", "find": "([a-z", "replace": ""}])
    check("invalid regex reported", bool(errs2))

    # bad backreference
    _c, errs3 = validate_rules([{"name": "y", "enabled": True, "type": "regex",
                                 "find": "abc", "replace": r"\1"}])
    check("bad backreference reported", bool(errs3))

    # empty-match guard
    _c, errs4 = validate_rules([{"name": "z", "enabled": True, "type": "regex",
                                 "find": "a*", "replace": "X"}])
    check("empty-matching pattern reported", bool(errs4))

    # literal backslash in a text replacement is not a regex escape
    c5, _ = validate_rules([{"name": "w", "enabled": True, "type": "text",
                             "find": "CRMDRM", "replace": r"C\RMDRM"}])
    out5, _h, _r = apply_rules("produced by CRMDRM", c5)
    check("literal backslash preserved", out5 == r"produced by C\RMDRM")

    # word boundary
    c6, _ = validate_rules([{"name": "v", "enabled": True, "type": "text",
                             "find": "crmdrm", "replace": "NEW",
                             "word_boundary": True}])
    out6, _h, _r = apply_rules("crmdrm and crmdrmbeats", c6)
    check("word boundary respected", out6 == "NEW and crmdrmbeats")

    # length guard
    long_desc = "x" * 4990 + " crmdrm"
    c7, _ = validate_rules([{"name": "u", "enabled": True, "type": "text",
                             "find": "crmdrm", "replace": "c" * 60}])
    _o, _h, rej7 = apply_rules(long_desc, c7)
    check("over-length result rejected", bool(rej7))

    # urls
    check("extract_urls finds 3", len(set(extract_urls(SAMPLE))) == 3)
    check("domain_of strips www", domain_of("https://www.beatstars.com/x") == "beatstars.com")

    # add_block
    t, err = add_block("hello", "-- footer --")
    check("add_block appends", t.endswith("-- footer --") and err is None)
    t2, err2 = add_block(t, "-- footer --")
    check("add_block refuses duplicate", err2 == "already present")
    _t3, err3 = add_block("x" * 4990, "y" * 100)
    check("add_block respects limit", err3 and "limit" in err3)

    # measured length
    check("emoji counts as 2 in utf-16", measured_len("a🔥") == 3)

    print()
    if fails:
        print(f"SELF-TEST FAILED: {fails} case(s).")
        return 1
    print("SELF-TEST PASSED.")
    return 0


def cli():
    ap = argparse.ArgumentParser(description="Bulk description rules.")
    ap.add_argument("--list", action="store_true", help="Show configured rules.")
    ap.add_argument("--check", action="store_true", help="Validate rules.json.")
    ap.add_argument("--test", action="store_true", help="Run rules against sample text.")
    ap.add_argument("--self-test", action="store_true", help="Run the engine tests.")
    args = ap.parse_args()

    if args.self_test:
        sys.exit(self_test())

    rules = load_rules()
    compiled, errors = validate_rules(rules)

    if args.list or args.check:
        print(f"{len(rules)} rule(s) in {RULES_FILE}, {len(compiled)} enabled\n")
        for r in rules:
            flag = "on " if r.get("enabled") else "off"
            print(f"  [{flag}] {r.get('name')}  ({r.get('type','text')})")
            print(f"          find    : {r.get('find')}")
            print(f"          replace : {r.get('replace')}")
            if r.get("protect"):
                print(f"          protect : {', '.join(r['protect'])}")
        print()
        if errors:
            print("PROBLEMS:")
            for e in errors:
                print("  -", e)
            sys.exit(1)
        print("All rules valid.")

    if args.test:
        out, hits, rej = apply_rules(SAMPLE, compiled)
        print("--- sample before ---");  print(SAMPLE)
        print("--- sample after ----");  print(out)
        print("hits      :", hits)
        print("rejections:", rej)

    if not any(vars(args).values()):
        ap.print_help()


if __name__ == "__main__":
    cli()
