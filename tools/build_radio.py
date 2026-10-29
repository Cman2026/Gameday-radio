"""Build radio.json: every Division I (FBS + FCS) football team mapped to its
TuneIn football station and current stream URLs. Runs on GitHub Actions."""
import json, re, time, urllib.parse, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (GamedayRadio directory builder)", "Origin": "https://cman2026.github.io"}
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
report = {"cors": {}, "unmatched": [], "notes": []}

def get(url, raw=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read()
        hdr = {k.lower(): v for k, v in r.headers.items()}
    return (body if raw else json.loads(body)), hdr

def teams_for(group):
    data, _ = get(f"{ESPN}/teams?groups={group}&limit=500")
    out = []
    for lg in data.get("sports", [{}])[0].get("leagues", []):
        for t in lg.get("teams", []):
            t = t["team"]
            out.append({"id": t["id"], "location": t.get("location", ""), "name": t.get("name", ""),
                        "display": t.get("displayName", ""), "short": t.get("shortDisplayName", ""),
                        "abbr": t.get("abbreviation", ""), "division": "FBS" if group == 80 else "FCS"})
    return out

def norm(s):
    s = s.lower().replace("&", "and")
    s = re.sub(r"\bst\.?\b", "state", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def tunein_search(q):
    url = "https://opml.radiotime.com/Search.ashx?" + urllib.parse.urlencode({"query": q, "render": "json"})
    data, hdr = get(url)
    report["cors"].setdefault("search", hdr.get("access-control-allow-origin"))
    items = []
    def walk(node):
        for o in node:
            if o.get("guide_id", "").startswith("s") and o.get("type") == "audio":
                items.append({"id": o["guide_id"], "text": o.get("text", ""), "subtext": o.get("subtext", "")})
            if o.get("children"):
                walk(o["children"])
    walk(data.get("body", []))
    return items

def tune(sid):
    url = f"https://opml.radiotime.com/Tune.ashx?id={sid}&render=json&formats=mp3,aac,hls"
    data, hdr = get(url)
    report["cors"].setdefault("tune", hdr.get("access-control-allow-origin"))
    return [b["url"] for b in data.get("body", []) if b.get("url")]

def pick(team, results):
    loc = norm(team["location"])
    best = None
    for r in results:
        t = norm(r["text"])
        if not t.endswith("football"):
            continue
        stem = t[: -len("football")].strip()
        score = 0
        if stem == loc: score = 100
        elif stem == norm(team["display"]): score = 95
        elif stem == norm(team["short"]): score = 90
        elif stem == norm(f'{team["location"]} {team["name"]}'): score = 90
        elif stem and (stem in loc or loc in stem) and abs(len(stem) - len(loc)) <= 6: score = 60
        if score and (not best or score > best[0]):
            best = (score, r)
    return best

teams = teams_for(80) + teams_for(81)
seen = set(); teams = [t for t in teams if not (t["id"] in seen or seen.add(t["id"]))]
report["notes"].append(f"{len(teams)} teams")
out = {}
for t in teams:
    queries = [f'{t["location"]} Football', f'{t["location"]} {t["name"]} Football']
    if "State" in t["location"]:
        queries.insert(1, t["location"].replace("State", "St.") + " Football")
    found = None
    for q in queries:
        try:
            res = tunein_search(q)
        except Exception as e:
            report["notes"].append(f"search fail {q}: {e}")
            time.sleep(1); continue
        b = pick(t, res)
        if b and (not found or b[0] > found[0]):
            found = b
        if found and found[0] >= 90:
            break
        time.sleep(0.25)
    entry = {"team": t["display"], "location": t["location"], "abbr": t["abbr"], "division": t["division"]}
    if found:
        r = found[1]
        entry.update({"tunein": r["id"], "station": r["text"], "match": found[0]})
        try:
            entry["streams"] = tune(r["id"])
        except Exception as e:
            entry["streams"] = []; report["notes"].append(f"tune fail {r['id']}: {e}")
        time.sleep(0.25)
    else:
        report["unmatched"].append(t["display"])
    out[t["id"]] = entry

json.dump({"built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "teams": out}, open("radio.json", "w"), indent=0, sort_keys=True)
report["matched"] = sum(1 for v in out.values() if v.get("tunein"))
report["with_streams"] = sum(1 for v in out.values() if v.get("streams"))
report["low_confidence"] = [f'{v["team"]} -> {v["station"]}' for v in out.values() if v.get("match", 100) < 90]
json.dump(report, open("radio-report.json", "w"), indent=1)
print(json.dumps({k: report[k] for k in ("cors", "matched", "with_streams")}, indent=1))
print("unmatched:", len(report["unmatched"]))
