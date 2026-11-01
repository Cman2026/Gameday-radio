"""Fetch moneylines from the major US sportsbooks for college football, basketball (men's and
women's) and baseball (The Odds API, one request per sport = 1 credit) and save odds.json for
the page. Only sports The Odds API lists as in season are fetched (that list is free).
Needs the ODDS_API_KEY secret."""
import json, os, sys, time, urllib.request

BOOKS = "draftkings,fanduel,betmgm,williamhill_us,espnbet,fanatics,betrivers,hardrockbet"
# The Odds API sport key -> the page's sport id
SPORTS = {"americanfootball_ncaaf": "fb", "basketball_ncaab": "mbb", "basketball_wncaab": "wbb", "baseball_ncaa": "bsb"}
key = os.environ.get("ODDS_API_KEY")
if not key:
    sys.exit("ODDS_API_KEY secret is not set")

def get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read()), r.headers.get("x-requests-remaining"), r.headers.get("x-requests-used")

active, left, used = get(f"https://api.the-odds-api.com/v4/sports?apiKey={key}")
active = {s["key"] for s in active if s.get("active")}
games = []
for sk, sid in SPORTS.items():
    if sk not in active:
        print(f"{sk}: not in season, skipped")
        continue
    try:
        data, left, used = get(f"https://api.the-odds-api.com/v4/sports/{sk}/odds"
                               f"?apiKey={key}&bookmakers={BOOKS}&markets=h2h&oddsFormat=american")
    except Exception as e:
        print(f"{sk}: {e}")
        continue
    n = 0
    for g in data:
        books = []
        for b in g.get("bookmakers", []):
            m = next((m for m in b.get("markets", []) if m["key"] == "h2h"), None)
            if not m:
                continue
            price = {o["name"]: o["price"] for o in m["outcomes"]}
            if g["home_team"] in price and g["away_team"] in price:
                books.append({"name": b["title"], "home": price[g["home_team"]], "away": price[g["away_team"]]})
        if books:
            games.append({"sport": sid, "home": g["home_team"], "away": g["away_team"], "start": g["commence_time"], "books": books})
            n += 1
    print(f"{sk}: {n} games with odds")
json.dump({"updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "credits_left": left, "games": games},
          open("odds.json", "w"), indent=0)
print(f"{len(games)} games with odds; credits used {used}, left {left}")
