"""The sports the site covers, for the game-time jobs (school feed finder, now-playing check,
listening check). Ids match the page's: fb, mbb, wbb, mhk, whk, wvb, bsb, sb.

Results for football are stored under the stream URL (as before); other sports under
"<sport>|<url>", since one station can carry football on Saturday and basketball that night.
"""
import json, re, urllib.request

ESPN = "https://site.api.espn.com/apis/site/v2/sports/"
UA = {"User-Agent": "Mozilla/5.0 (GamedayRadio game-time jobs)"}

SPORTS = {
    #  id: (ESPN path, scoreboard group queries, words a school site / LEANplayer uses for it)
    "fb":  ("football/college-football", ["groups=80&", "groups=81&"]),
    "mbb": ("basketball/mens-college-basketball", ["groups=50&"]),
    "wbb": ("basketball/womens-college-basketball", ["groups=50&"]),
    "mhk": ("hockey/mens-college-hockey", [""]),
    "whk": ("hockey/womens-college-hockey", [""]),
    "wvb": ("volleyball/womens-college-volleyball", [""]),
    "bsb": ("baseball/college-baseball", [""]),
    "sb":  ("baseball/college-softball", [""]),
}
NAMES = {"fb": "Football", "mbb": "Men's Basketball", "wbb": "Women's Basketball", "mhk": "Men's Hockey",
         "whk": "Women's Hockey", "wvb": "Volleyball", "bsb": "Baseball", "sb": "Softball"}

# SIDEARM "sport_shortname" values (fball, mbball, wbball, wvball, mhockey, ...).
SIDEARM = {
    "fb":  re.compile(r"^(football|fball|fb)$", re.I),
    "mbb": re.compile(r"^(mbball|mbb|mbask|mbasket|mbasketball|basketball-?men|men-?s-?basketball|m-?basketball|mens-?basketball|basketball)$", re.I),
    "wbb": re.compile(r"^(wbball|wbb|wbask|wbasket|wbasketball|basketball-?women|women-?s-?basketball|w-?basketball|womens-?basketball)$", re.I),
    "mhk": re.compile(r"^(mhockey|mhock|mih|hockey-?men|m-?hockey|mens-?ice-?hockey|ice-?hockey|hockey)$", re.I),
    "whk": re.compile(r"^(whockey|whock|wih|hockey-?women|w-?hockey|womens-?ice-?hockey)$", re.I),
    "wvb": re.compile(r"^(wvball|vball|wvb|vb|volleyball|volleyball-?women|wvolley|w-?volleyball|womens-?volleyball)$", re.I),
    "bsb": re.compile(r"^(baseball|bsb|base)$", re.I),
    "sb":  re.compile(r"^(softball|sball|sb)$", re.I),
}
# LEANplayer stream URLs carry ?sport=CODE
LEAN = {"fb": "FB", "mbb": "MBB", "wbb": "WBB", "mhk": "MHOC|MIH|HOC", "whk": "WHOC|WIH", "wvb": "WVB|VB", "bsb": "BSB|BASE", "sb": "SB|SOFT"}
# Button text on school audio pages
LABEL = {"fb": "Football", "mbb": "Basketball", "wbb": "Basketball", "mhk": "Hockey", "whk": "Hockey",
         "wvb": "Volleyball", "bsb": "Baseball", "sb": "Softball"}


def key(sport, url):
    return url if sport == "fb" else f"{sport}|{url}"


def scoreboards(sports=None):
    """[(sport, event)] for every event on today's scoreboards."""
    out = []
    for sid in sports or SPORTS:
        path, groups = SPORTS[sid]
        seen = set()
        for g in groups:
            try:
                with urllib.request.urlopen(urllib.request.Request(f"{ESPN}{path}/scoreboard?{g}limit=900", headers=UA), timeout=25) as r:
                    for e in json.loads(r.read()).get("events", []):
                        if e["id"] not in seen:
                            seen.add(e["id"]); out.append((sid, e))
            except Exception as ex:
                print("scoreboard error", sid, g, str(ex)[:80])
    return out


def live(sports=None):
    return [(s, e) for s, e in scoreboards(sports) if e.get("status", {}).get("type", {}).get("state") == "in"]


def norm(x):
    x = (x or "").lower().replace("&", " and ")
    x = re.sub(r"\bst\.?\b", "state", x)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x)).strip()


def directory_index(teams):
    index = {}
    for t in teams:
        for n in [t.get("school")] + (t.get("names") or []):
            if n:
                index.setdefault(norm(n), t)
    return index


def find_team(index, tm):
    for n in (tm.get("location"), tm.get("displayName"), tm.get("shortDisplayName"),
              f"{tm.get('location', '')} {tm.get('name', '')}", tm.get("abbreviation")):
        if norm(n) in index:
            return index[norm(n)]
    return None


def streams_for(team, sport):
    """The streams the page would try for this sport: school game feeds only if they're for this sport."""
    feeds = team.get("game_feeds") or []
    mine = (team.get("game_feeds_sport") or "fb") == sport
    return [u for u in (team.get("streams") or []) if mine or u not in feeds]
