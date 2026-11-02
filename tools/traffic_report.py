"""Weekly traffic report from GoatCounter (gamedayradiolive.goatcounter.com).

Compares the last 7 days (Monday-Sunday, Eastern) with the 7 before, and lists the busiest
day, top pages and referrers, listens by sport and team, failed connections, devices and
countries. Prints a Markdown report (also to the Actions run summary). Needs the
GOATCOUNTER_TOKEN secret (a GoatCounter API key with "Read statistics").
"""
import datetime as dt, json, os, sys, time, urllib.error, urllib.parse, urllib.request

SITE = "https://gamedayradiolive.goatcounter.com/api/v0"
TOKEN = os.environ.get("GOATCOUNTER_TOKEN")
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = dt.timezone(dt.timedelta(hours=-5))
SPORT = {"fb": "Football", "mbb": "Men's basketball", "wbb": "Women's basketball", "mhk": "Men's hockey",
         "whk": "Women's hockey", "wvb": "Volleyball", "bsb": "Baseball", "sb": "Softball"}


def api(path, **q):
    url = f"{SITE}/{path}?" + urllib.parse.urlencode(q)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:  # rate limited: wait and retry
                time.sleep(5 * (attempt + 1)); continue
            if e.code == 404:  # a period before the site existed: nothing counted
                return {}
            body = e.read().decode("utf-8", "ignore")[:300]
            raise RuntimeError(f"GoatCounter {e.code} for {path} {q}: {body}") from None
    raise RuntimeError("GoatCounter kept rate-limiting")


def n(x):
    return x.get("count", x.get("count_unique", 0)) if isinstance(x, dict) else 0


def week(end):
    """Monday 12 AM to the next Monday 12 AM, Eastern time (GoatCounter wants full timestamps)."""
    start = end - dt.timedelta(days=7)
    utc = lambda d: dt.datetime(d.year, d.month, d.day, tzinfo=ET).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"start": utc(start), "end": utc(end), "_first": start, "_last": end - dt.timedelta(days=1)}


def hits(rng):
    out, after = [], None
    for _ in range(20):
        q = dict(rng, limit=100, include_events="true")
        if after: q["exclude_paths"] = ",".join(str(h["path_id"]) for h in out if "path_id" in h)
        d = api("stats/hits", **q)
        out += d.get("hits") or []
        if not d.get("more"): break
        after = True
    return out


def pct(a, b):
    if not b: return "new" if a else "–"
    return f"{(a - b) / b * 100:+.0f}%"


def probe():
    for path, q in [("me", {}), ("sites", {}), ("stats/total", {"start": "2026-10-26", "end": "2026-11-01"}),
                    ("stats/total", {"start": "2026-10-26T00:00:00Z", "end": "2026-11-02T00:00:00Z"}),
                    ("stats/hits", {"start": "2026-10-26T00:00:00Z", "end": "2026-11-02T00:00:00Z", "limit": 5})]:
        try:
            print("OK ", path, q, json.dumps(api(path, **q))[:400])
        except Exception as e:
            print("ERR", path, q, e)


def main():
    if os.environ.get("PROBE"):
        return probe()
    if not TOKEN:
        print("GOATCOUNTER_TOKEN secret is not set. Add it in the repo: Settings → Secrets and variables → Actions."); sys.exit(0)
    today = dt.datetime.now(ET).date()
    end = today - dt.timedelta(days=today.weekday())          # this Monday
    if os.environ.get("CURRENT_WEEK"):                         # test run: the week in progress
        end += dt.timedelta(days=7)
    this, last = week(end), week(end - dt.timedelta(days=7))
    rng = lambda w: {"start": w["start"], "end": w["end"]}
    t1, t0 = api("stats/total", **rng(this)), api("stats/total", **rng(last))
    h1, h0 = hits(rng(this)), hits(rng(last))
    pages = [h for h in h1 if not h.get("event")]
    events = [h for h in h1 if h.get("event")]
    ev0 = [h for h in h0 if h.get("event")]
    listens = [h for h in events if h["path"].startswith("listen/")]
    listens0 = sum(n(h) for h in ev0 if h["path"].startswith("listen/"))
    fails = [h for h in events if h["path"].startswith("listen-failed/")]
    norad = [h for h in events if h["path"].startswith("no-radio/")]
    taps = [h for h in events if h["path"].startswith("sport/")]

    visits1, visits0 = n(t1.get("total", t1)) if isinstance(t1.get("total"), dict) else t1.get("total", 0), \
                       n(t0.get("total", t0)) if isinstance(t0.get("total"), dict) else t0.get("total", 0)
    days = {}
    for s in t1.get("stats") or []:
        try: d = dt.date.fromisoformat(s.get("day", ""))
        except Exception: continue
        if this["_first"] <= d <= this["_last"]:
            days[s["day"]] = s.get("daily", 0)
    busiest = max(days.items(), key=lambda kv: kv[1]) if days else None

    def fmt_day(d):
        return dt.date.fromisoformat(d).strftime("%A, %b %-d")

    L = []
    L.append(f"## Gameday Radio Live: week of {this['_first'].strftime('%b %-d')} – {this['_last'].strftime('%b %-d')}")
    L.append("")
    L.append(f"- **Visits:** {visits1:,} ({pct(visits1, visits0)} vs. the week before: {visits0:,})")
    L.append(f"- **Listens started:** {sum(n(h) for h in listens):,} ({pct(sum(n(h) for h in listens), listens0)} vs. {listens0:,})")
    if busiest: L.append(f"- **Busiest day:** {fmt_day(busiest[0])} with {busiest[1]:,} visits")
    if days:
        L.append("- **By day:** " + " · ".join(f"{dt.date.fromisoformat(d).strftime('%a')} {v:,}" for d, v in sorted(days.items())))
    by_sport = {}
    for h in listens:
        sp = h["path"].split("/")[1]
        by_sport[sp] = by_sport.get(sp, 0) + n(h)
    if by_sport:
        L.append("")
        L.append("**Listens by sport:** " + " · ".join(f"{SPORT.get(k, k)} {v:,}" for k, v in sorted(by_sport.items(), key=lambda kv: -kv[1])))
    if listens:
        L.append("")
        L.append("**Most-listened teams:**")
        for h in sorted(listens, key=lambda h: -n(h))[:10]:
            _, sp, team = h["path"].split("/", 2)
            L.append(f"1. {team} ({SPORT.get(sp, sp)}): {n(h):,}")
    if taps:
        L.append("")
        L.append("**Sport tile taps:** " + " · ".join(f"{SPORT.get(h['path'].split('/')[1], h['path'])} {n(h):,}" for h in sorted(taps, key=lambda h: -n(h))))
    if fails or norad:
        L.append("")
        L.append("**Where listeners hit a wall** (worth fixing first):")
        for h in sorted(fails, key=lambda h: -n(h))[:6]:
            _, sp, team = h["path"].split("/", 2); L.append(f"- {team} ({SPORT.get(sp, sp)}): didn't connect ×{n(h)}")
        for h in sorted(norad, key=lambda h: -n(h))[:6]:
            _, sp, team = h["path"].split("/", 2); L.append(f"- {team} ({SPORT.get(sp, sp)}): tapped with no radio ×{n(h)}")
    try:
        refs = api("stats/toprefs", **rng(this), limit=6).get("stats") or []
        refs = [r for r in refs if r.get("name")]
        if refs:
            L.append("")
            L.append("**Where visitors came from:** " + " · ".join(f"{r['name']} {n(r):,}" for r in refs))
    except Exception as e:
        print("referrers:", e, file=sys.stderr)
    for page, label in (("systems", "Devices"), ("locations", "Countries")):
        try:
            st = api(f"stats/{page}", **rng(this), limit=5).get("stats") or []
            tot = sum(n(x) for x in st) or 1
            if st:
                L.append(f"**{label}:** " + " · ".join(f"{x.get('name') or 'Unknown'} {round(n(x) / tot * 100)}%" for x in st))
        except Exception as e:
            print(page, e, file=sys.stderr)
    report = "\n".join(L)
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(report + "\n")


if __name__ == "__main__":
    main()
