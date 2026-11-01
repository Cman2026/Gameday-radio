# Saves a snapshot of each sport's ESPN feeds (for testing the page offline).
import json, os, urllib.request, datetime as dt
B = "https://site.api.espn.com/apis/site/v2/sports/"
L = {"fb":("football/college-football","groups=80&"),"mbb":("basketball/mens-college-basketball","groups=50&"),"wbb":("basketball/womens-college-basketball","groups=50&"),
     "mhk":("hockey/mens-college-hockey",""),"whk":("hockey/womens-college-hockey",""),"wvb":("volleyball/womens-college-volleyball",""),
     "bsb":("baseball/college-baseball",""),"sb":("baseball/college-softball","")}
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent":"Mozilla/5.0"}), timeout=40) as r: return json.load(r)
    except Exception as e: return {"_err": str(e)}
out = {}
for k,(p,g) in L.items():
    sb = get(f"{B}{p}/scoreboard?{g}limit=900"); out[f"{p}/scoreboard?{g}limit=900"] = sb
    out[f"{p}/groups"] = get(f"{B}{p}/groups")
    evs = sb.get("events", [])
    pick = [e for e in evs if e["status"]["type"]["state"]=="in"][:2] or [e for e in evs if e["status"]["type"]["state"]=="post"][:1]
    for e in pick: out[f"{p}/summary?event={e['id']}"] = get(f"{B}{p}/summary?event={e['id']}")
    cal = ((sb.get("leagues") or [{}])[0].get("calendar") or [])
    now = dt.datetime.utcnow()
    for c in cal:
        if isinstance(c, str):
            t = dt.datetime.strptime(c[:10], "%Y-%m-%d")
            if now - dt.timedelta(hours=12) < t < now + dt.timedelta(days=4):
                key = c[:10].replace("-","")
                out[f"{p}/scoreboard?{g}dates={key}&limit=900"] = get(f"{B}{p}/scoreboard?{g}dates={key}&limit=900")
os.makedirs("tools/fixtures", exist_ok=True)
json.dump(out, open("tools/fixtures/espn.json","w"))
print("saved", len(out), {k: len(v.get("events",[])) for k,v in out.items() if "scoreboard" in k})
