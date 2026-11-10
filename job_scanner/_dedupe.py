#!/usr/bin/env python3
# ponytail: run-scoped dedupe helper for /scan-jobs. Loads seen hashes; hashes candidates.
import json, sys, hashlib

SEEN = "state/seen.jsonl"

def load_seen(path=SEEN):
    urls, contents = set(), set()
    try:
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            for k in ("url_hash", "hash"):
                if o.get(k):
                    urls.add(o[k])
            if o.get("content_hash"):
                contents.add(o["content_hash"])
    except FileNotFoundError:
        pass
    return urls, contents

def h(s):
    return hashlib.sha1(s.lower().encode()).hexdigest()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "count"
    urls, contents = load_seen()
    if cmd == "count":
        print(f"url_hashes:{len(urls)} content_hashes:{len(contents)}")
    elif cmd == "check":
        # args: url, company, title  -> prints NEW or SEEN
        url, company, title = sys.argv[2], sys.argv[3], sys.argv[4]
        uh = h(url); ch = h(company + "|" + title)
        print("SEEN" if (uh in urls or ch in contents) else "NEW", uh, ch)
