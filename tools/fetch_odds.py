"""Fetch moneylines from the major US sportsbooks for every college football game
(The Odds API, one request = 1 credit) and save odds.json for the page.
Needs the ODDS_API_KEY secret."""
import json, os, sys, time, urllib.request

BOOKS = "draftkings,fanduel,betmgm,williamhill_us,espnbet,fanatics,betrivers,hardrockbet"
key = os.environ.get("ODDS_API_KEY")
if not key:
    sys.exit("ODDS_API_KEY secret is not set")
url = ("https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"
       f"?apiKey={key}&bookmakers={BOOKS}&markets=h2h&oddsFormat=american")
with urllib.request.urlopen(url, timeout=30) as r:
    data = json.loads(r.read())
    left, used = r.headers.get("x-requests-remaining"), r.headers.get("x-requests-used")
games = []
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
        games.append({"home": g["home_team"], "away": g["away_team"], "start": g["commence_time"], "books": books})
json.dump({"updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "credits_left": left, "games": games},
          open("odds.json", "w"), indent=0)
print(f"{len(games)} games with odds; credits used {used}, left {left}")
