import json, urllib.request, datetime as dt
B = "https://site.api.espn.com/apis/site/v2/sports/"
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent":"Mozilla/5.0"}), timeout=30) as r: return json.load(r)
    except Exception as e: return {"_err": str(e)}
t = dt.date.today()
for s in ["baseball/college-softball","softball/college-softball","softball/womens-college-softball"]:
    d = get(f"{B}{s}/scoreboard"); L=(d.get("leagues") or [{}])[0]
    print("SOFT", s, d.get("_err") or (len(d.get("events",[])), L.get("calendarEndDate"), (L.get("calendar") or [None])[0]))
for s in ["basketball/mens-college-basketball","hockey/mens-college-hockey","volleyball/womens-college-volleyball","baseball/college-baseball"]:
    for q in [f"dates={t+dt.timedelta(days=1):%Y%m%d}&limit=500", f"dates={t+dt.timedelta(days=1):%Y%m%d}&groups=50&limit=500", "dates=20270213&limit=500", "dates=2027&limit=5"]:
        d = get(f"{B}{s}/scoreboard?{q}"); L=(d.get("leagues") or [{}])[0]; cal=L.get("calendar") or []
        print(s, q, d.get("_err") or ("events", len(d.get("events",[])), "cal", cal[:1], cal[-1:] if cal and isinstance(cal[-1],str) else "", "end", L.get("calendarEndDate")))
    g = get(f"{B}{s}/groups")
    if "_err" in g: print(" groups ERR", g["_err"]); continue
    def walk(x, depth=0):
        for c in x.get("children",[]) or []:
            print("  "*depth, " grp", c.get("name"), c.get("abbreviation"), "teams", len(c.get("teams",[]) or []))
            walk(c, depth+1)
    for top in g.get("groups",[]): print(" TOP", top.get("name"), len(top.get("teams",[]) or [])); walk(top)
# basketball live situation & plays coordinate & summary header
d = get(f"{B}volleyball/womens-college-volleyball/scoreboard")
for e in d.get("events",[])[:2]:
    c=e["competitions"][0]; print("VB", e["status"]["type"]["shortDetail"], [ (x["team"]["abbreviation"], x.get("score"), [l.get("value") for l in x.get("linescores",[])]) for x in c["competitors"]], json.dumps(c.get("situation"))[:200])
d = get(f"{B}hockey/mens-college-hockey/scoreboard")
for e in d.get("events",[])[:2]:
    c=e["competitions"][0]; print("HK", e["status"]["type"]["shortDetail"], e["status"].get("displayClock"), [(x["team"]["abbreviation"], x.get("score"), x["team"].get("color")) for x in c["competitors"]])
