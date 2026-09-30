"""R2. Корпус постов за N суток с реакциями, типом и видом поста.

Вход:   файл со списком каналов (по одному @handle или handle в строке; '#' — комментарий).
Выход:  data/r/corpus/<handle>.json.gz — метаданные канала + посты. Уже собранные каналы
        пропускаются, поэтому процесс можно прерывать и перезапускать.

Режимы:
  python tools/r2_crawl.py LIST [--days 14] [--max-pages 60]
  python tools/r2_crawl.py LIST --meta          # только первая страница (метаданные + последние ~20 постов)

Что сохраняется по посту: id, время (UTC, секунды), просмотры, текст, ссылки (url + текст ссылки),
@упоминания, хэштеги, медиа (фото/альбом/видео/кружок/документ/аудио/опрос/стикер/не поддерживается),
превью ссылки, форвард (имя, url), ответ, via-бот, подпись автора, пометка «изменено»,
реакции по типам (эмодзи / custom / платные звёзды) с корректным разбором «1.04K».
Строго последовательно, пауза ≥2 с: параллельные запросы к t.me портят блок реакций (docs/06 §2.8).
"""
import gzip, json, os, re, sys, time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTD = os.path.join(ROOT, "data", "r", "corpus")
LOG = os.path.join(ROOT, "data", "r", "crawl_log.jsonl")
os.makedirs(OUTD, exist_ok=True)

args = sys.argv[1:]
LIST = args[0]
DAYS = float(args[args.index("--days") + 1]) if "--days" in args else 14.0
MAXP = int(args[args.index("--max-pages") + 1]) if "--max-pages" in args else 60
META_ONLY = "--meta" in args
DELAY = 2.2
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
S = requests.Session()
S.headers["User-Agent"] = UA
_last = [0.0]


def get(url):
    for attempt in range(4):
        w = DELAY - (time.time() - _last[0])
        if w > 0:
            time.sleep(w)
        try:
            r = S.get(url, timeout=30, allow_redirects=True)
            _last[0] = time.time()
            if r.status_code == 429:
                time.sleep(60 * (attempt + 1))
                continue
            return r
        except Exception as e:
            _last[0] = time.time()
            print(f"  ! {url}: {e}", file=sys.stderr)
            time.sleep(10 * (attempt + 1))
    return None


def num(s):
    """'1.04K' → 1040, '3 205' → 3205, '2.1M' → 2100000."""
    if s is None:
        return None
    s = re.sub(r"[\s  ]", "", str(s)).upper().replace(",", ".")
    m = re.search(r"([\d.]+)([KMB]?)$", s)
    if not m:
        return None
    try:
        return round(float(m.group(1)) * {"K": 1e3, "M": 1e6, "B": 1e9}.get(m.group(2), 1))
    except ValueError:
        return None


def meta(soup):
    g = lambda sel: (soup.select_one(sel).get_text(" ", strip=True) if soup.select_one(sel) else None)
    counters = {}
    for c in soup.select(".tgme_channel_info_counter"):
        v, t = c.select_one(".counter_value"), c.select_one(".counter_type")
        if v and t:
            counters[t.get_text(strip=True)] = num(v.get_text(strip=True))
    return {"title": g(".tgme_channel_info_header_title"),
            "description": g(".tgme_channel_info_description"),
            "verified": bool(soup.select_one(".tgme_channel_info_header_title .verified-icon")),
            "counters": counters}


def reactions(w):
    br, paid = {}, 0
    for rc in w.select(".tgme_reaction"):
        n = num(rc.get_text(" ", strip=True).split()[-1] if rc.get_text(strip=True) else None)
        if n is None:
            continue
        cls = rc.get("class", [])
        if "tgme_reaction_paid" in cls:
            paid += n
            continue
        if rc.find("tg-emoji"):
            key = "custom"
        else:
            b = rc.find("b")
            key = b.get_text(strip=True) if b else "?"
        br[key] = br.get(key, 0) + n
    return br, paid


def post(w, ch):
    pid = w["data-post"].split("/")[-1]
    t = w.select_one("time[datetime]")
    body = w.select_one("div.js-message_text")
    links, mentions = [], []
    if body:
        for a in body.find_all("a", href=True):
            h = a["href"]
            if h.startswith("http"):
                links.append([h, a.get_text(" ", strip=True)[:80]])
            m = re.search(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{3,})", h)
            if m:
                mentions.append(m.group(1))
    text = body.get_text("\n", strip=True) if body else ""
    mentions += re.findall(r"(?<![\w/@])@([A-Za-z0-9_]{4,})", text)
    grouped = w.select_one(".tgme_widget_message_grouped_layer")
    media = {
        "photo": len(w.select(".tgme_widget_message_photo_wrap")),
        "video": len(w.select(".tgme_widget_message_video_player")),
        "round": len(w.select(".tgme_widget_message_roundvideo_player")),
        "document": len(w.select(".tgme_widget_message_document")),
        "audio": len(w.select(".tgme_widget_message_voice, .tgme_widget_message_audio")),
        "poll": len(w.select(".tgme_widget_message_poll")),
        "sticker": len(w.select(".tgme_widget_message_sticker_wrap")),
        "unsupported": len(w.select(".message_media_not_supported")),
        "album_items": len(grouped.find_all(recursive=False)) if grouped else 0,
    }
    lp = w.select_one("a.tgme_widget_message_link_preview")
    preview = None
    if lp:
        sn, tt = lp.select_one(".link_preview_site_name"), lp.select_one(".link_preview_title")
        preview = {"url": lp.get("href"), "site": sn.get_text(strip=True) if sn else None,
                   "title": tt.get_text(strip=True)[:200] if tt else None}
    fwd = w.select_one("a.tgme_widget_message_forwarded_from_name")
    fwd_div = w.select_one(".tgme_widget_message_forwarded_from")
    rp = w.select_one("a.tgme_widget_message_reply")
    via = w.select_one(".tgme_widget_message_via_bot")
    sig = w.select_one(".tgme_widget_message_from_author")
    v = w.select_one(".tgme_widget_message_views")
    meta_txt = w.select_one(".tgme_widget_message_meta")
    br, paid = reactions(w)
    return {
        "id": int(pid), "dt": t["datetime"] if t else None,
        "views": num(v.get_text(strip=True)) if v else None,
        "text": text, "links": links, "mentions": list(dict.fromkeys(mentions)),
        "hashtags": re.findall(r"#([\wА-Яа-яЁё]+)", text),
        "media": {k: x for k, x in media.items() if x}, "preview": preview,
        "fwd_name": (fwd.get_text(strip=True) if fwd else
                     (fwd_div.get_text(" ", strip=True).replace("Forwarded from", "").strip() if fwd_div else None)),
        "fwd_url": fwd.get("href") if fwd else None,
        "reply_url": rp.get("href") if rp else None,
        "via_bot": via.get_text(strip=True) if via else None,
        "signature": sig.get_text(strip=True) if sig else None,
        "edited": bool(meta_txt and "edited" in meta_txt.get_text(" ", strip=True).lower()),
        "rx": br, "rx_total": sum(br.values()), "rx_paid_stars": paid,
        "has_rx_block": bool(w.select_one(".tgme_widget_message_reactions")),
    }


def crawl(ch):
    since = datetime.now(timezone.utc) - timedelta(days=DAYS)
    posts, before, info, pages, stop = {}, None, None, 0, "window"
    while pages < (1 if META_ONLY else MAXP):
        r = get(f"https://t.me/s/{ch}" + (f"?before={before}" if before else ""))
        pages += 1
        if r is None:
            stop = "net"
            break
        if "/s/" not in r.url:
            stop = "no_web_preview"
            break
        soup = BeautifulSoup(r.text, "html.parser")
        if info is None:
            info = meta(soup)
        wraps = [w for w in soup.select("div.tgme_widget_message[data-post]")
                 if w["data-post"].split("/")[-1].isdigit()]
        if not wraps:
            stop = "empty" if pages == 1 else "end"
            break
        dts = []
        for w in wraps:
            p = post(w, ch)
            posts[p["id"]] = p
            if p["dt"]:
                dts.append(datetime.fromisoformat(p["dt"]))
        oldest = min(int(w["data-post"].split("/")[-1]) for w in wraps)
        if before and oldest >= before:
            stop = "end"
            break
        before = oldest
        if dts and min(dts) < since:
            break
    else:
        stop = "max_pages" if not META_ONLY else "meta"
    keep = [p for p in posts.values() if META_ONLY or (p["dt"] and datetime.fromisoformat(p["dt"]) >= since)]
    return {"handle": ch, "meta": info, "posts": sorted(keep, key=lambda p: p["id"]),
            "crawl": {"fetched_at": datetime.now(timezone.utc).isoformat(), "days": DAYS, "pages": pages,
                      "stop": stop, "meta_only": META_ONLY, "posts_seen": len(posts)}}


if __name__ == "__main__":
    handles = []
    for line in open(LIST, encoding="utf-8"):
        h = line.split("#")[0].strip().lstrip("@")
        if h and h not in handles:
            handles.append(h)
    suffix = ".meta.json.gz" if META_ONLY else ".json.gz"
    t0 = time.time()
    for i, h in enumerate(handles, 1):
        path = os.path.join(OUTD, h + suffix)
        if os.path.exists(path):
            continue
        res = crawl(h)
        with gzip.open(path + ".tmp", "wt", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False)
        os.replace(path + ".tmp", path)
        c = res["crawl"]
        subs = (res["meta"] or {}).get("counters", {}).get("subscribers")
        rx_ok = sum(1 for p in res["posts"] if p["rx_total"] or p["rx_paid_stars"])
        line = {"i": i, "n": len(handles), "handle": h, "subs": subs, "posts": len(res["posts"]),
                "pages": c["pages"], "stop": c["stop"], "posts_with_rx": rx_ok,
                "elapsed_min": round((time.time() - t0) / 60, 1)}
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        print(json.dumps(line, ensure_ascii=False), file=sys.stderr)
