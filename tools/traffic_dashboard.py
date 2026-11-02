"""Turn the weekly report's JSON line into the two files the traffic dashboard reads.

Usage: python3 tools/traffic_dashboard.py WEEK_JSON [OLD_WEEKS_JSON] OUT_DIR
  WEEK_JSON       the line after "JSON " in the Weekly traffic report run log, saved to a file
  OLD_WEEKS_JSON  the dashboard's current weeks.json (omit, or "-", the first time)
Writes OUT_DIR/weeks.json (one row per week, history kept) and OUT_DIR/latest.json
(the newest week broken down: days, sports, teams, tile taps, dead ends, referrers,
devices, countries).
"""
import datetime as dt, json, os, sys


def label(a, b):
    a, b = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    return f"{a.strftime('%b %-d')} – {b.strftime('%b %-d')}"


def main():
    week_path, old_path, out = (sys.argv[1], "-", sys.argv[2]) if len(sys.argv) == 3 else sys.argv[1:4]
    w = json.load(open(week_path))
    weeks = json.load(open(old_path)) if old_path != "-" and os.path.exists(old_path) else []
    weeks = [r for r in weeks if r["week"] != w["week_start"]]
    weeks.append({"week": w["week_start"], "week_label": label(w["week_start"], w["week_end"]),
                  "visits": w["visits"], "visits_prev": w["visits_prev"],
                  "listens": w["listens"], "listens_prev": w["listens_prev"]})
    weeks.sort(key=lambda r: r["week"])

    rows = []
    add = lambda section, name, value, detail="", share=None: rows.append(
        {"section": section, "name": name, "detail": detail, "value": value, "share": share})
    for d in w["days"]:
        add("day", d["date"], d["visits"], dt.date.fromisoformat(d["date"]).strftime("%a"))
    for s in w["sports"]: add("sport", s["sport"], s["listens"])
    for t in w["teams"]: add("team", t["team"], t["listens"], t["sport"])
    for t in w["taps"]: add("tap", t["sport"], t["taps"])
    for x in w["walls"]: add("wall", f"{x['team']} ({x['sport']})", x["count"], x["problem"])
    for r in w["referrers"]: add("referrer", r["name"], r["visits"])
    for d in w["devices"]: add("device", d["name"], d["visits"], share=d["share"])
    for c in w["countries"]: add("country", c["name"], c["visits"], share=c["share"])

    os.makedirs(out, exist_ok=True)
    json.dump(weeks, open(os.path.join(out, "weeks.json"), "w"), indent=1)
    json.dump(rows, open(os.path.join(out, "latest.json"), "w"), indent=1)
    print(f"weeks.json: {len(weeks)} weeks; latest.json: {len(rows)} rows")


if __name__ == "__main__":
    main()
