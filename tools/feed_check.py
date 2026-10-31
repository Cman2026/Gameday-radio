"""List every audio event in SIDEARM's live-events feed for the given schools (by athletics site).
Usage: python tools/feed_check.py "School A" "School B" ...  -> feed-check.json"""
import json, sys, urllib.request
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36", "Accept": "application/json"}
src = json.load(open("tools/radio-sources.json"))
out = {}
for s in src:
    if not any(w.lower() in s["school"].lower() for w in sys.argv[1:]) or not s.get("athletics_site"):
        continue
    site = s["athletics_site"].rstrip("/")
    evs = []
    for q in ("type=Live&count=24&tab=1&pageSize=24", "type=Live&count=24"):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{site}/services/allaccess.ashx/media/get?{q}", headers=UA), timeout=15) as r:
                d = json.loads(r.read())
            d = json.loads(d) if isinstance(d, str) else d
            evs = [{k: e.get(k) for k in ("title", "date_utc", "sport_shortname", "format", "free", "premium", "app_exclusive", "formats", "is_live")} for e in d]
            break
        except Exception as ex:
            evs = [{"error": str(ex)[:100]}]
    out[s["school"]] = evs
    print(s["school"], len(evs))
json.dump(out, open("feed-check.json", "w"), indent=1)
