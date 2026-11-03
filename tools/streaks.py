"""Win streaks for men's and women's basketball -> streaks.json.

ESPN's scoreboard doesn't say how many games in a row a team has won, so this walks back through
the season's daily scoreboards (one request per day, regular season and postseason only) and
counts each team's run of wins since its last loss. The page features games with a team on a
streak of 6 or more. Runs once a day; only streaks of 3+ are kept to keep the file small.
"""
import datetime as dt, json, time, urllib.request

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/"
UA = {"User-Agent": "Mozilla/5.0 (GamedayRadio streaks)"}
LEAGUES = {"mbb": "mens-college-basketball", "wbb": "womens-college-basketball"}
DAYS_BACK = 75  # long enough for any streak that matters; the season resets them anyway


def get(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                return json.loads(r.read())
        except Exception as ex:
            if i == 2:
                print("skip", url, str(ex)[:80])
            time.sleep(2)
    return {}


def streaks(path):
    games = {}  # team id -> [(start time, won)]
    today = dt.date.today()
    for back in range(1, DAYS_BACK + 1):
        day = today - dt.timedelta(days=back)
        for e in get(f"{ESPN}{path}/scoreboard?groups=50&dates={day:%Y%m%d}&limit=900").get("events", []):
            if e.get("season", {}).get("type") not in (2, 3) or e.get("status", {}).get("type", {}).get("state") != "post":
                continue
            for c in e["competitions"][0]["competitors"]:
                games.setdefault(str(c["team"]["id"]), []).append((e["date"], bool(c.get("winner"))))
    out = {}
    for tid, gs in games.items():
        n = 0
        for _, won in sorted(gs, reverse=True):
            if not won:
                break
            n += 1
        if n >= 3:
            out[tid] = n
    return out


if __name__ == "__main__":
    data = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    for lid, path in LEAGUES.items():
        data[lid] = streaks(path)
        top = sorted(data[lid].items(), key=lambda kv: -kv[1])[:5]
        print(lid, len(data[lid]), "teams on 3+ win streaks; longest:", top)
    json.dump(data, open("streaks.json", "w"), separators=(",", ":"))
