"""R6. Раскрытие ссылок в рекламных постах до конечного домена (сокращатели, трекинг бирж).

Берёт все ссылки из маркированных рекламных постов корпуса, кроме t.me, и проходит редиректы
(HEAD, при отказе — GET со stream). Кэш: data/r/ad_url_resolved.json (повторный запуск дописывает).
Вежливо: не чаще раза в секунду на хост.
"""
import json, os, sys, time
from urllib.parse import urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT, is_marked_ad, load  # noqa: E402

OUT = os.path.join(ROOT, "data", "r", "ad_url_resolved.json")
res = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
S = requests.Session()
S.headers["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
last = {}
C = load()
CHS = {c["handle"]: c for c in json.load(open(os.path.join(ROOT, "data", "r", "channels.json"), encoding="utf-8"))} \
    if os.path.exists(os.path.join(ROOT, "data", "r", "channels.json")) else {}
SKIP = ("aliexpress", "ali.click", "market.yandex", "%d0%90%d0%9b%d0%98")   # скидочные партнёрки считаются отдельно
urls = []
for ch, d in C.items():
    if (CHS.get(ch, {}).get("deal_share") or 0) >= 0.3:
        continue
    for p in d["posts"]:
        if is_marked_ad(p):
            for u, _ in p.get("links") or []:
                u = u.replace("&amp;", "&")
                h = urlparse(u).netloc.lower()
                if h and "t.me" not in h and u not in res and not any(x in u.lower() for x in SKIP):
                    urls.append(u)
urls = list(dict.fromkeys(urls))
print(f"к раскрытию: {len(urls)}", file=sys.stderr)
for k, u in enumerate(urls, 1):
    h = urlparse(u).netloc.lower()
    w = 1.0 - (time.time() - last.get(h, 0))
    if w > 0:
        time.sleep(w)
    final, chain = None, []
    try:
        r = S.head(u, allow_redirects=True, timeout=15)
        if r.status_code >= 400 or urlparse(r.url).netloc == h:
            r = S.get(u, allow_redirects=True, timeout=15, stream=True)
            r.close()
        final = r.url
        chain = [x.url for x in r.history]
    except Exception as e:
        final = f"ERR:{type(e).__name__}"
    last[h] = time.time()
    res[u] = {"final": final, "final_host": urlparse(final).netloc.lower() if final and not final.startswith("ERR") else None,
              "hops": len(chain)}
    if k % 50 == 0:
        json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  {k}/{len(urls)}", file=sys.stderr)
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
print("done", len(res), file=sys.stderr)
