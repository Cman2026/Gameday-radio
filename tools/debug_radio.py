import json, urllib.request, urllib.parse
UA={"User-Agent":"Mozilla/5.0","Origin":"https://cman2026.github.io"}
out={}
def get(url):
    try:
        req=urllib.request.Request(url,headers=UA)
        with urllib.request.urlopen(req,timeout=20) as r:
            b=r.read().decode("utf-8","replace"); h={k.lower():v for k,v in r.headers.items()}
        return {"status":200,"cors":h.get("access-control-allow-origin"),"ctype":h.get("content-type"),"body":b[:4000]}
    except Exception as e:
        return {"error":str(e)}
E="https://site.api.espn.com/apis/site/v2/sports/football/college-football"
for g in (80,81):
    r=get(f"{E}/teams?groups={g}&limit=500"); 
    try:
        d=json.loads(urllib.request.urlopen(urllib.request.Request(f"{E}/teams?groups={g}&limit=500",headers=UA),timeout=20).read())
        teams=d["sports"][0]["leagues"][0]["teams"]; out[f"teams{g}"]={"n":len(teams),"sample":[t["team"]["location"] for t in teams[:8]]}
    except Exception as e: out[f"teams{g}"]=str(e)
q="Iowa State Football"
out["opml_search"]=get("https://opml.radiotime.com/Search.ashx?"+urllib.parse.urlencode({"query":q,"render":"json"}))
out["opml_search_station"]=get("https://opml.radiotime.com/Search.ashx?"+urllib.parse.urlencode({"query":q,"render":"json","types":"station"}))
out["api_search"]=get("https://api.tunein.com/profiles?"+urllib.parse.urlencode({"fullTextSearch":"true","query":q,"formats":"mp3,aac,ogg,flash,hls","partnerId":"RadioTime","version":"6.0"}))
out["opml_tune"]=get("https://opml.radiotime.com/Tune.ashx?id=s273715&render=json&formats=mp3,aac,hls")
out["opml_tune_mtsu"]=get("https://opml.radiotime.com/Tune.ashx?id=s273724&render=json&formats=mp3,aac,hls")
out["opml_describe"]=get("https://opml.radiotime.com/Describe.ashx?id=s273715&render=json")
json.dump(out,open("radio-debug.json","w"),indent=1)
