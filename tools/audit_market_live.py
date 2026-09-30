"""audit_market_live.py — экономная живая проверка (строго последовательно, >=4 с).

Кэш/результат: audit_parts/audit_market_live.json (повторный запуск пропускает готовое).
Задачи:
  pages  — telegram.menu (пагинация), tgme.app search/c/tech/g/advertisers/ads
  dead   — 5 «мёртвых» каналов docs/07 §4.3
  sample — 40 случайных из 321 канала tgme-поиска (seed 20260930)
Запуск: python tools/audit_market_live.py [pages|dead|sample|extra ...]
"""
import json, os, re, sys, time, random
import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTF = os.path.join(ROOT, "audit_parts", "audit_market_live.json")
DELAY = 4.0
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                  "Accept-Language": "ru,en;q=0.8"})
try:
    RES = json.load(open(OUTF, encoding="utf-8"))
except Exception:
    RES = {}
_last = [0.0]


def save():
    json.dump(RES, open(OUTF, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def get(url):
    w = DELAY - (time.time() - _last[0])
    if w > 0:
        time.sleep(w)
    try:
        r = S.get(url, timeout=30, allow_redirects=True)
        _last[0] = time.time()
        return r
    except Exception as e:
        _last[0] = time.time()
        print("  !", url, e, file=sys.stderr)
        return None


def snum(s):
    s = re.sub(r"[\s  ]", "", str(s)).upper().replace(",", ".")
    m = re.match(r"^([\d.]+)([KMB])?$", s)
    if not m:
        return None
    try:
        return float(m.group(1)) * {"K": 1e3, "M": 1e6, "B": 1e9}.get(m.group(2), 1)
    except ValueError:
        return None


def cyr_share(t):
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", t)
    if not letters:
        return None
    return round(sum(1 for c in letters if re.match(r"[А-Яа-яЁё]", c)) / len(letters), 3)


def tme(h):
    r = get(f"https://t.me/s/{h}")
    if r is None:
        return {"err": "net"}
    d = {"status": r.status_code, "final_url": r.url}
    s = BeautifulSoup(r.text, "html.parser")
    if "/s/" not in r.url:
        # нет превью канала: бот, пользователь, группа или несуществующий
        ex = s.select_one(".tgme_page_extra")
        tt = s.select_one(".tgme_page_title")
        ds = s.select_one(".tgme_page_description")
        act = s.select_one(".tgme_action_button_new")
        d.update({"kind": "no_preview",
                  "title": tt.get_text(" ", strip=True) if tt else None,
                  "extra": ex.get_text(" ", strip=True) if ex else None,
                  "desc": (ds.get_text(" ", strip=True)[:300] if ds else None),
                  "action": act.get_text(" ", strip=True) if act else None})
        return d
    tt = s.select_one(".tgme_channel_info_header_title")
    ds = s.select_one(".tgme_channel_info_description")
    cnt = {}
    for c in s.select(".tgme_channel_info_counter"):
        v = c.select_one(".counter_value")
        t = c.select_one(".counter_type")
        if v and t:
            cnt[t.get_text(strip=True)] = snum(v.get_text(strip=True))
    msgs = s.select("div.tgme_widget_message[data-post]")
    texts = [m.select_one(".tgme_widget_message_text") for m in msgs]
    texts = [t.get_text(" ", strip=True) for t in texts if t]
    dts = sorted(x.get("datetime") for x in s.select(".tgme_widget_message_date time[datetime]"))
    d.update({"kind": "channel",
              "title": tt.get_text(" ", strip=True) if tt else None,
              "desc": ds.get_text(" ", strip=True)[:400] if ds else None,
              "counters": cnt, "n_posts": len(msgs),
              "newest": dts[-1] if dts else None, "oldest_on_page": dts[0] if dts else None,
              "cyr_share": cyr_share(" ".join(texts) + " " + (d.get("desc") or "")),
              "sample_text": " | ".join(t[:160] for t in texts[-4:]),
              "erid_on_page": sum(1 for m in msgs if "erid" in str(m).lower())})
    return d


def run_pages():
    P = RES.setdefault("pages", {})
    urls = {
        "menu_p1": "https://telegram.menu/channels/tech",
        "menu_p2": "https://telegram.menu/channels/tech?page=2",
        "tgme_search_nn": "https://tgme.app/search?q=" + requests.utils.quote("нейросети"),
        "tgme_c_tech": "https://tgme.app/c/tech",
        "tgme_g_adv": "https://tgme.app/g/advertisers",
        "tgme_ads": "https://tgme.app/ads",
    }
    for k, u in urls.items():
        if k in P:
            continue
        r = get(u)
        if r is None:
            P[k] = {"err": "net"}
            save()
            continue
        raw = r.text
        t = re.sub(r"<!--.*?-->", " ", BeautifulSoup(raw, "html.parser").get_text(" ", strip=True))
        P[k] = {"status": r.status_code, "final_url": r.url, "bytes": len(raw),
                "text": t[:60000],
                "hrefs_page": sorted(set(re.findall(r'href="([^"]*page[^"]*)"', raw)))[:40]}
        save()
        print(k, r.status_code, len(raw), file=sys.stderr)


DEAD = ["birds_announcement", "respawn_media", "blink_en", "bbqcointeam", "rideonwaves"]


def run_list(key, handles):
    X = RES.setdefault(key, {})
    for h in handles:
        if h in X and "err" not in X[h]:
            continue
        X[h] = tme(h)
        save()
        print(key, h, X[h].get("kind"), X[h].get("newest"), X[h].get("counters"), file=sys.stderr)


def sample_handles():
    md = json.load(open(os.path.join(ROOT, "data", "market_deep.json"), encoding="utf-8"))
    hs = sorted({x["handle"] for v in md["tgme_search"].values() for x in v})
    return random.Random(20260930).sample(hs, 40)


if __name__ == "__main__":
    what = sys.argv[1:] or ["pages", "dead", "sample"]
    if "pages" in what:
        run_pages()
    if "dead" in what:
        run_list("dead", DEAD)
    if "sample" in what:
        run_list("sample", sample_handles())
    if "extra" in what:
        run_list("extra", [a for a in sys.argv[sys.argv.index("extra") + 1:]])
    save()


def run_menu_pages(pages):
    P = RES.setdefault("menu_pages", {})
    for p in pages:
        k = str(p)
        if k in P and "err" not in P[k]:
            continue
        u = "https://telegram.menu/channels/tech" + ("" if p == 1 else f"/page/{p}")
        r = get(u)
        if r is None:
            P[k] = {"err": "net"}
            save()
            continue
        t = re.sub(r"<!--.*?-->", " ", BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True))
        items = [(h, snum(v)) for h, v in
                 re.findall(r"@([A-Za-z0-9_]{3,})\s*•\s*([\d\s ]+)", t)]
        P[k] = {"status": r.status_code, "url": r.url, "items": items,
                "text": t[:30000]}
        save()
        print("menu page", p, r.status_code, len(items),
              items[:1], items[-1:], file=sys.stderr)


if __name__ == "__main__" and "menupages" in sys.argv:
    run_menu_pages([int(x) for x in sys.argv[sys.argv.index("menupages") + 1:]])
    save()


def run_raw(key, urls):
    X = RES.setdefault(key, {})
    for u in urls:
        if u in X and "err" not in X[u]:
            continue
        r = get(u)
        if r is None:
            X[u] = {"err": "net"}
        else:
            t = re.sub(r"<!--.*?-->", " ", BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True))
            X[u] = {"status": r.status_code, "final_url": r.url, "bytes": len(r.text), "text": t[:20000]}
        save()
        print(key, u, X[u].get("status"), X[u].get("bytes"), file=sys.stderr)


if __name__ == "__main__" and "raw" in sys.argv:
    run_raw("raw", sys.argv[sys.argv.index("raw") + 1:])
    save()
