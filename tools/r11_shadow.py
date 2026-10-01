"""R11. Теневая контент-машина: в реальном времени следит за источниками и за каналами-конкурентами.

Что меряем: для каждой новости — когда машина МОГЛА БЫ её заметить (момент нашего опроса,
на котором элемент источника впервые появился) и когда её опубликовал первый русский канал.
Разница = запас времени машины до первого конкурента (без учёта времени на рерайт и публикацию).

Два потока:
  * источники (RSS/API/sitemap с точным временем; список ниже), опрос каждые POLL_FEEDS секунд;
  * каналы-конкуренты на t.me/s/ — строго последовательно, пауза TG_DELAY, полный круг ~1–2 мин.

Запуск:  python tools/r11_shadow.py HOURS [channels.txt]
Пишет:   data/r/shadow/items.jsonl (элементы источников), data/r/shadow/tg.jsonl (посты каналов)
"""
import calendar, hashlib, json, os, re, sys, threading, time
from datetime import datetime, timezone

import feedparser, requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "r", "shadow")
os.makedirs(OUT, exist_ok=True)
HOURS = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
CH_FILE = sys.argv[2] if len(sys.argv) > 2 else None
POLL_FEEDS, TG_DELAY = 60, 1.6
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

FEEDS = {
    # лаборатории и вендоры
    "openai": "https://openai.com/news/rss.xml",
    "google_ai": "https://blog.google/technology/ai/rss/",
    "deepmind": "https://deepmind.google/blog/rss.xml",
    "nvidia_dev": "https://developer.nvidia.com/blog/feed/",
    "huggingface_blog": "https://huggingface.co/blog/feed.xml",
    "anthropic_sitemap": "https://www.anthropic.com/sitemap.xml",
    "simonwillison": "https://simonwillison.net/atom/everything/",
    "the_decoder": "https://the-decoder.com/feed/",
    # агрегаторы
    "hn_new": "https://hn.algolia.com/api/v1/search_by_date?tags=story&hitsPerPage=50",
    "techmeme": "https://www.techmeme.com/feed.xml",
    "reddit_localllama": "https://www.reddit.com/r/LocalLLaMA/new/.rss?limit=25",
    "reddit_openai": "https://www.reddit.com/r/OpenAI/new/.rss?limit=25",
    # англоязычные СМИ
    "verge": "https://www.theverge.com/rss/index.xml",
    "techcrunch": "https://techcrunch.com/feed/",
    "9to5google": "https://9to5google.com/feed/",
    "9to5mac": "https://9to5mac.com/feed/",
    "engadget": "https://www.engadget.com/rss.xml",
    "ars": "https://feeds.arstechnica.com/arstechnica/index",
    "register": "https://www.theregister.com/headlines.atom",
    "wired": "https://www.wired.com/feed/rss",
    "tomshardware": "https://www.tomshardware.com/feeds/all",
    "thehackernews": "https://feeds.feedburner.com/TheHackersNews",
    "gsmarena": "https://www.gsmarena.com/rss-news-reviews.php3",
    "electrek": "https://electrek.co/feed/",
    # русские СМИ
    "3dnews": "https://3dnews.ru/news/rss/",
    "ixbt": "https://www.ixbt.com/export/news.rss",
    "4pda": "https://4pda.to/feed/",
    "cnews": "https://www.cnews.ru/inc/rss/news.xml",
    "habr_news": "https://habr.com/ru/rss/news/",
    "securitylab": "https://www.securitylab.ru/_services/export/rss/",
    "vcru": "https://vc.ru/rss",
    "overclockers": "https://overclockers.ru/rss/all.rss",
    "opennet": "https://www.opennet.ru/opennews/opennews_all.rss",
    "rb_ru": "https://rb.ru/feeds/all/",
    "kommersant": "https://www.kommersant.ru/RSS/news.xml",
    "lenta": "https://lenta.ru/rss/news",
    "rbc": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
    "ria": "https://ria.ru/export/rss2/archive/index.xml",
    "tass": "https://tass.ru/rss/v2.xml",
    "interfax": "https://www.interfax.ru/rss.asp",
}
SLOW = {"reddit_localllama": 300, "reddit_openai": 300, "anthropic_sitemap": 180, "techmeme": 120}

STOP = threading.Event()
LOCK = threading.Lock()


def write(name, rec):
    with LOCK, open(os.path.join(OUT, name), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def now():
    return datetime.now(timezone.utc).timestamp()


def feeds_loop():
    S = requests.Session()
    S.headers["User-Agent"] = UA
    seen, last = {}, {}
    while not STOP.is_set():
        for name, url in FEEDS.items():
            if STOP.is_set():
                break
            if now() - last.get(name, 0) < SLOW.get(name, POLL_FEEDS):
                continue
            last[name] = now()
            try:
                r = S.get(url, timeout=25)
            except Exception:
                continue
            t_seen = now()
            items = []
            if name == "hn_new":
                for h in r.json().get("hits", []):
                    items.append((h["objectID"], h.get("title") or "", "", h.get("url") or "", h["created_at_i"]))
            elif name == "anthropic_sitemap":
                for loc in re.findall(r"<loc>([^<]+/news/[^<]+)</loc>", r.text):
                    items.append((loc, loc.rsplit("/", 1)[-1].replace("-", " "), "", loc, None))
            else:
                for e in feedparser.parse(r.content).entries:
                    pt = e.get("published_parsed") or e.get("updated_parsed")
                    items.append((e.get("id") or e.get("link"), e.get("title", ""),
                                  re.sub(r"<[^>]+>", " ", e.get("summary", ""))[:400], e.get("link", ""),
                                  calendar.timegm(pt) if pt else None))
            first_poll = name not in seen
            s = seen.setdefault(name, set())
            for iid, title, summ, link, pub in items:
                k = hashlib.md5(f"{name}|{iid}".encode()).hexdigest()
                if k in s:
                    continue
                s.add(k)
                # элементы, бывшие в ленте при первом опросе, помечаем: момент их появления неизвестен
                write("items.jsonl", {"src": name, "id": iid, "title": title, "summary": summ, "link": link,
                                      "pub_t": pub, "seen_t": t_seen, "baseline": first_poll})
            time.sleep(0.3)
        time.sleep(5)


def tg_loop(channels):
    S = requests.Session()
    S.headers["User-Agent"] = UA
    seen = {}
    while not STOP.is_set():
        for ch in channels:
            if STOP.is_set():
                break
            t0 = now()
            try:
                r = S.get(f"https://t.me/s/{ch}", timeout=25)
            except Exception:
                time.sleep(TG_DELAY)
                continue
            t_seen = now()
            soup = BeautifulSoup(r.text, "html.parser")
            first_poll = ch not in seen
            s = seen.setdefault(ch, set())
            for w in soup.select("div.tgme_widget_message[data-post]"):
                pid = w["data-post"].split("/")[-1]
                if not pid.isdigit() or pid in s:
                    continue
                s.add(pid)
                tt = w.select_one("time[datetime]")
                body = w.select_one("div.js-message_text")
                fwd = w.select_one(".tgme_widget_message_forwarded_from")
                write("tg.jsonl", {"ch": ch, "id": int(pid), "dt": tt["datetime"] if tt else None, "seen_t": t_seen,
                                   "baseline": first_poll, "fwd": fwd.get_text(" ", strip=True) if fwd else None,
                                   "text": body.get_text("\n", strip=True)[:1500] if body else ""})
            time.sleep(max(0, TG_DELAY - (now() - t0)))


if __name__ == "__main__":
    channels = []
    if CH_FILE:
        channels = [l.split("#")[0].strip().lstrip("@") for l in open(CH_FILE, encoding="utf-8")]
        channels = [c for c in channels if c]
    th = [threading.Thread(target=feeds_loop, daemon=True)]
    if channels:
        th.append(threading.Thread(target=tg_loop, args=(channels,), daemon=True))
    for t in th:
        t.start()
    end = now() + HOURS * 3600
    while now() < end:
        time.sleep(30)
    STOP.set()
    time.sleep(3)
    print("done", file=sys.stderr)
