import json, urllib.request, datetime as dt
B = "https://site.api.espn.com/apis/site/v2/sports/"
S = ["basketball/mens-college-basketball","basketball/womens-college-basketball","hockey/mens-college-hockey","hockey/womens-college-hockey","volleyball/womens-college-volleyball","baseball/college-baseball","softball/college-softball","lacrosse/mens-college-lacrosse"]
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent":"Mozilla/5.0"}), timeout=30) as r: return json.load(r)
    except Exception as e: return {"_err": str(e)}
today = dt.date.today()
rng = f"{today:%Y%m%d}-{today+dt.timedelta(days=8):%Y%m%d}"
for s in S:
    print("=====", s)
    for q in ["limit=500", "groups=50&limit=500", f"dates={rng}&limit=900", f"dates={rng}&groups=50&limit=900"]:
        d = get(f"{B}{s}/scoreboard?{q}")
        if "_err" in d: print(q, "ERR", d["_err"]); continue
        L = (d.get("leagues") or [{}])[0]
        ev = d.get("events", [])
        cal = L.get("calendar") or []
        print(q, "| events", len(ev), "| season", L.get("season",{}).get("year"), L.get("season",{}).get("type",{}).get("name") if isinstance(L.get("season",{}).get("type"),dict) else L.get("season",{}).get("type"),
              "| calStart", L.get("calendarStartDate"), "calEnd", L.get("calendarEndDate"), "| calType", L.get("calendarType"), "| cal n", len(cal), "first", cal[:2] if cal and isinstance(cal[0],str) else (cal[0].get("label") if cal else None), "last", cal[-1] if cal and isinstance(cal[-1],str) else None)
        if ev and q=="limit=500":
            e = ev[0]; c = e["competitions"][0]
            print("  sample:", e["name"], e["date"], e["status"]["type"].get("shortDetail"), "| comp keys", sorted(c.keys()))
            print("  situation:", json.dumps(c.get("situation"))[:400])
            t = c["competitors"][0]
            print("  competitor keys", sorted(t.keys()), "| team keys", sorted(t["team"].keys()), "| conf", t["team"].get("conferenceId"), "| records", [r.get("summary") for r in t.get("records",[])][:2], "| rank", t.get("curatedRank"))
            print("  status", json.dumps(e["status"])[:300])
            sm = get(f"{B}{s}/summary?event={e['id']}")
            print("  summary keys", sorted(sm.keys()) if "_err" not in sm else sm)
            if "_err" not in sm:
                print("  plays n", len(sm.get("plays") or []), "sample", json.dumps((sm.get("plays") or [{}])[-1])[:400])
                bs = sm.get("boxscore",{}).get("teams") or []
                if bs: print("  box stats", [ (x.get("name") or x.get("label"), x.get("displayValue")) for x in bs[0].get("statistics",[])][:14])
    # live/in-season events today states
groups = get(B+"basketball/mens-college-basketball/groups")
print("MBB groups", json.dumps(groups)[:600])
