import json, re, os, sys, time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from urllib.parse import urlparse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SINCE = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)   # 2 weeks for stable link stats

RU = ["whackdoor", "bugnotfeature", "technomedia", "tehnochat", "exploitex",
      "naebnet", "trends", "tlive", "technomotel", "hiaimedia",
      "xor_journal", "ai_newz", "data_secrets", "seeallochnaya", "denissexy",
      "neuraldvig", "gptpublic", "rozetked", "d_code", "cgevent",
      "NeuralShit", "tproger", "ai_machinelearning_big_data"]

EN = ["anthropic", "aipost", "hiaimediaen", "TheHackerNews", "GitHub",
      "news_crypto", "TechDaily", "bleepingcomputer", "perplexity_ai",
      "machinelearningresearchnews", "levelsio", "tldrtech", "AInews_en", "ml_news"]

S = requests.Session()
S.headers.update({"User-Agent": UA})

TGREF = re.compile(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{3,})", re.I)


def fetch(username, max_pages=40):
    posts, before, pages = [], None, 0
    while pages < max_pages:
        url = f"https://t.me/s/{username}" + (f"?before={before}" if before else "")
        try:
            r = S.get(url, timeout=30)
        except Exception as e:
            print(f"  ! {username}: {e}", file=sys.stderr)
            break
        if r.status_code != 200:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        wraps = soup.select("div.tgme_widget_message[data-post]")
        if not wraps:
            break
        page, dts = [], []
        for w in wraps:
            pid = w.get("data-post", "").split("/")[-1]
            if not pid.isdigit():
                continue
            t = w.select_one("time[datetime]")
            if not t:
                continue
            dt = datetime.fromisoformat(t["datetime"].replace("Z", "+00:00"))
            dts.append(dt)
            if dt < SINCE:
                continue
            body = w.select_one("div.js-message_text")
            txt = body.get_text(" ", strip=True) if body else ""
            if not txt:
                continue

            links, mentions = [], []
            if body:
                for a in body.find_all("a", href=True):
                    h = a["href"]
                    if h.startswith("http"):
                        links.append(h)
                    m = TGREF.search(h)
                    if m:
                        mentions.append(m.group(1))
            # bare @mentions in text
            mentions += re.findall(r"(?<![\w/@])@([A-Za-z0-9_]{4,})", txt)
            # reply-to = citation of a specific post
            reply = ""
            rp = w.select_one("a.tgme_widget_message_reply")
            if rp and rp.get("href"):
                reply = rp["href"]
            # forward: the <a> that carries the source handle+post id
            fwd_href, fwd_txt = "", ""
            fa = w.select_one("a.tgme_widget_message_forwarded_from_name")
            if fa:
                fwd_href = fa.get("href", "")
                fwd_txt = fa.get_text(strip=True)
            else:
                fb = w.select_one("div.tgme_widget_message_forwarded_from")
                if fb:
                    fwd_txt = fb.get_text(" ", strip=True).replace("Forwarded from", "").strip()
            views = w.select_one("span.tgme_widget_message_views")

            page.append({
                "id": pid, "dt": dt.isoformat(), "text": txt[:1200],
                "links": links, "mentions": list(dict.fromkeys(mentions)),
                "reply": reply, "fwd_url": fwd_href, "fwd_name": fwd_txt,
                "views": views.get_text(strip=True) if views else "",
            })
        posts += page
        ids = [int(x) for x in
               [wx.get("data-post", "").split("/")[-1] for wx in wraps]
               if x.isdigit()]
        if not ids:
            break
        oldest = min(ids)
        if before and oldest >= before:
            break
        before = oldest
        if dts and min(dts) < SINCE:
            break
        pages += 1
        time.sleep(0.45)
    return posts


if __name__ == "__main__":
    out = {}
    for u in RU + EN:
        ps = fetch(u)
        out[u] = ps
        nl = sum(len(p["links"]) for p in ps)
        nm = sum(len(p["mentions"]) for p in ps)
        print(f"  {u:32s} posts={len(ps):4d} links={nl:4d} mentions={nm:4d}", file=sys.stderr)
    with open(os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"), "links.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("saved", sum(len(v) for v in out.values()), file=sys.stderr)
