"""Featured / Editor's Pick report -> out/featured-report.html (a private page, not on the website).

Every time the page features a game it records an analytics event "featured/<sport>/<game id>" whose
title carries the reason, itemized, e.g.
  Featured | #14 Miami 53 at #1 Florida 61 | 2nd 11:15 | 70 pts: Ranked vs ranked +30, Close finish +40
This reads those events from GoatCounter day by day (Eastern time) and writes a page listing every
pick, newest day first, so it's easy to review why a game was picked. Runs every morning.
"""
import datetime as dt, html, json, os, re, sys

sys.path.insert(0, os.path.dirname(__file__))
from traffic_report import api, ET  # same GoatCounter account and token

DAYS = int(os.environ.get("DAYS") or 21)
SPORT = {"fb": "Football", "mbb": "Men's basketball", "wbb": "Women's basketball", "mhk": "Men's hockey",
         "whk": "Women's hockey", "bsb": "Baseball", "sb": "Softball"}


def day_hits(day):
    utc = lambda d: dt.datetime(d.year, d.month, d.day, tzinfo=ET).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    q, out, seen = {"start": utc(day), "end": utc(day + dt.timedelta(days=1)), "limit": 100}, [], []
    for _ in range(30):
        d = api("stats/hits", **(dict(q, exclude_paths=",".join(seen)) if seen else q))
        for h in d.get("hits") or []:
            seen.append(str(h.get("path_id", "")))
            out.append(h)
        if not d.get("more"):
            break
    return out


def parse(h):
    m = re.match(r"^/?featured/([a-z]+)/(\w+)$", h.get("path") or "")
    if not m:
        return None
    parts = [p.strip() for p in (h.get("title") or "").split("|")]
    slot, game, clock, why = (parts + ["", "", "", ""])[:4]
    pts = re.match(r"(\d+)\s*pts", why)
    items = [(r.strip(), int(p)) for r, p in re.findall(r"([^,:]+?)\s*\+(\d+)", why.split(":", 1)[-1])]
    return {"sport": m.group(1), "id": m.group(2), "slot": slot or "Featured", "game": game, "clock": clock,
            "points": int(pts.group(1)) if pts else sum(p for _, p in items), "items": items,
            "devices": h.get("count", 0)}


def page(days):
    esc = html.escape
    rows = []
    for day, picks in days:
        if not picks:
            continue
        rows.append(f'<h2>{esc(day.strftime("%A, %B %-d"))} <span class="n">{len(picks)} pick{"s" if len(picks) != 1 else ""}</span></h2>')
        for p in sorted(picks, key=lambda x: (x["sport"], x["slot"] != "Editor's Pick", -x["points"])):
            chips = "".join(f'<span class="it">{esc(r)} <b>+{v}</b></span>' for r, v in p["items"])
            rows.append(f'''<article class="pick{' ed' if p['slot'] == "Editor's Pick" else ''}">
  <div class="top"><span class="slot">{esc(p['slot'])}</span><span class="sp">{esc(SPORT.get(p['sport'], p['sport']))}</span><span class="pts">{p['points']} pts</span></div>
  <div class="game">{esc(p['game'])}</div>
  <div class="when">Picked at {esc(p['clock'] or '?')} · <a href="https://www.espn.com/{'college-football' if p['sport'] == 'fb' else 'mens-college-basketball' if p['sport'] == 'mbb' else 'womens-college-basketball' if p['sport'] == 'wbb' else 'college-sports'}/game/_/gameId/{esc(p['id'])}">ESPN game page</a></div>
  <div class="items">{chips or '<span class="it">No itemized reason recorded</span>'}</div>
</article>''')
    body = "\n".join(rows) or '<p class="empty">No games have been featured in this period yet.</p>'
    updated = dt.datetime.now(ET).strftime("%B %-d, %-I:%M %p ET")
    return f'''<title>Featured Picks Report</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
/* One reading column of pick cards, grouped by day; Editor's Picks outlined in the site's gold. */
:root{{--bg:#F2F3F5;--surface:#fff;--line:#E2E5EA;--text:#11161D;--muted:#5F6B7A;--accent:#A86400;--soft:#FFF3DF}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#0F141A;--surface:#171D25;--line:#29313B;--text:#ECEFF3;--muted:#9AA5B2;--accent:#F2A93B;--soft:#2A2110;color-scheme:dark}}}}
:root[data-theme="dark"]{{--bg:#0F141A;--surface:#171D25;--line:#29313B;--text:#ECEFF3;--muted:#9AA5B2;--accent:#F2A93B;--soft:#2A2110;color-scheme:dark}}
body{{background:var(--bg);color:var(--text);font:400 15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:760px;margin:0 auto;padding-block:24px 48px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}}
h1{{margin:0 0 4px;font-size:26px;text-wrap:balance}} .sub{{color:var(--muted);margin:0 0 18px;max-width:65ch}}
details{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin-bottom:18px}}
summary{{font-weight:600;cursor:pointer}} table{{border-collapse:collapse;margin-top:8px;font-size:14px}} td{{padding:3px 12px 3px 0}} td+td{{text-align:right;font-variant-numeric:tabular-nums}}
h2{{font-size:18px;margin:26px 0 10px;display:flex;gap:10px;align-items:baseline}} h2 .n{{font-size:13px;color:var(--muted);font-weight:500}}
.pick{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:10px;display:grid;gap:6px;min-width:0}}
.pick.ed{{border-color:var(--accent)}}
.top{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px}}
.slot{{font-weight:700;color:var(--accent)}} .sp{{color:var(--muted)}} .pts{{margin-left:auto;font-weight:700;font-variant-numeric:tabular-nums}}
.game{{font-weight:600;font-size:16px}} .when{{color:var(--muted);font-size:13px}} .when a{{color:var(--accent)}}
.items{{display:flex;flex-wrap:wrap;gap:6px}} .it{{background:var(--soft);border-radius:999px;padding:2px 10px;font-size:13px}}
.empty{{color:var(--muted)}}
a:focus-visible,summary:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
</style>
<main>
<h1>Featured Picks Report</h1>
<p class="sub">Every game the site featured, and why, for the last {DAYS} days. Updated {esc(updated)}. "Picked at" is the game clock when it first qualified; points are what it had then.</p>
<details><summary>How games are picked</summary>
<p>Featured holds up to 4 games worth 40+ points; once all 4 are taken, a game worth 60+ becomes the Editor's Pick (one at a time). A picked game stays until it's final.</p>
<table>
<tr><td>Overtime</td><td>50</td></tr><tr><td>Close finish (close and late)</td><td>40</td></tr>
<tr><td>Ranked vs ranked (top 10 vs top 10)</td><td>30 (40)</td></tr><tr><td>Comeback</td><td>30</td></tr>
<tr><td>Upset watch (ranked team top 10)</td><td>25 (35)</td></tr><tr><td>Rivalry</td><td>20</td></tr>
<tr><td>Unbeaten late in the season</td><td>15</td></tr><tr><td>Close in the second half</td><td>10</td></tr>
<tr><td>Win streak of 6+ (basketball; +2 per extra win)</td><td>10–25</td></tr><tr><td>One Top 25 team (top 10)</td><td>5 (10)</td></tr>
</table></details>
{body}
</main>
'''


def main():
    today = dt.datetime.now(ET).date()
    days = []
    for back in range(0, DAYS):
        day = today - dt.timedelta(days=back)
        picks = {}
        for h in day_hits(day):
            p = parse(h)
            if p:
                picks.setdefault((p["sport"], p["id"]), p)  # one line per game per day
        days.append((day, list(picks.values())))
        print(day, len(picks), "picks")
    # Written for the private report only; nothing here is published on the website.
    os.makedirs("out", exist_ok=True)
    open("out/featured-report.html", "w").write(page(days))
    json.dump([{"day": str(d), "picks": p} for d, p in days if p], open("out/featured-log.json", "w"), indent=1)


def from_log(path, out):
    """Rebuild the page from a saved featured-log.json (used to fill Connor's private report page)."""
    data = json.load(open(path))
    days = [(dt.date.fromisoformat(d["day"]), d["picks"]) for d in data]
    for p in (x for _, ps in days for x in ps):
        p["items"] = [tuple(i) for i in p["items"]]
    open(out, "w").write(page(days))


if __name__ == "__main__":
    if len(sys.argv) == 3:
        from_log(sys.argv[1], sys.argv[2])
    else:
        main()
