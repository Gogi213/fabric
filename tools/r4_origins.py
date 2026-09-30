"""R4. Внешние первоисточники сюжетов за 14 суток.

Для каждого сюжета из data/r/stories.json (в ≥ MIN_CH каналах):
  1. якоря из текста первого поста: латинские слова (бренды, модели), числа/версии,
     кириллические имена собственные;
  2. поиск Google News (RU и, если есть латинские якоря, EN) в окне [первый пост − 3 сут; + 1 сут]
     и Hacker News (Algolia, полный архив);
  3. найденная публикация считается тем же сюжетом, если косинус заголовка к посту ≥ MATCH_SIM
     (многоязычная модель) и есть общий якорь;
  4. «волна СМИ» = медиана трёх самых ранних совпавших публикаций (самая ранняя бывает с ошибочной датой).

Выход: data/r/origins.json. Запуск: python tools/r4_origins.py [MIN_CH=3] [LIMIT=400]
Кэш запросов: data/r/origins_cache.json (повторный запуск не ходит в сеть за уже найденным).
"""
import calendar, json, os, re, statistics as st, sys, time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import feedparser, numpy as np, requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT  # noqa: E402

D = os.path.join(ROOT, "data", "r")
MIN_CH = int(sys.argv[1]) if len(sys.argv) > 1 else 3
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 400
MATCH_SIM = 0.60
S = requests.Session()
S.headers["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
STOP_LAT = set("the and for new with from this that your what how are was has have its into over after about more "
               "than will just can not you all out now one two use app apps model update release today first open "
               "video free best top news pro max ultra plus mini".split())
STOP_CYR = set("Это Как Что Теперь Также Если Когда После Сегодня Новый Новая Новые Для При Вот Все Всё Уже Там".split())


def anchors(t):
    lat = [w for w in re.findall(r"\b[A-Za-z][A-Za-z0-9.+-]{2,}\b", t) if w.lower() not in STOP_LAT]
    ver = re.findall(r"\b[A-Za-z]+[- ]?\d[\w.]*\b|\b\d+(?:[.,]\d+)?\s?(?:%|млрд|млн|тыс|\$)", t)
    cyr = [w for w in re.findall(r"(?<=[^.!?\n]\s)([А-ЯЁ][а-яё]{3,})", t) if w not in STOP_CYR]
    seen, out = set(), []
    for w in ver + lat + cyr:
        k = w.lower()
        if k not in seen:
            seen.add(k)
            out.append(w)
    return out, lat, cyr


def gnews(q, lang, t0, t1, cache):
    key = f"gn|{lang}|{q}|{t0:%Y-%m-%d}|{t1:%Y-%m-%d}"
    if key in cache:
        return cache[key]
    hl = "en-US&gl=US&ceid=US:en" if lang == "en" else "ru&gl=RU&ceid=RU:ru"
    url = (f"https://news.google.com/rss/search?q={quote(q + f' after:{t0:%Y-%m-%d} before:{t1:%Y-%m-%d}')}&hl={hl}")
    out = []
    for attempt in range(3):
        try:
            r = S.get(url, timeout=30)
            if r.status_code == 200:
                for e in feedparser.parse(r.content).entries:
                    if e.get("published_parsed"):
                        out.append({"title": e.title, "src": (e.get("source") or {}).get("title"),
                                    "t": calendar.timegm(e.published_parsed), "link": e.get("link")})
                break
        except Exception:
            pass
        time.sleep(10 * (attempt + 1))
    time.sleep(2.0)
    cache[key] = out
    return out


def hn(q, t0, t1, cache):
    key = f"hn|{q}|{t0:%Y-%m-%d}"
    if key in cache:
        return cache[key]
    out = []
    try:
        r = S.get("https://hn.algolia.com/api/v1/search", timeout=30,
                  params={"query": q, "tags": "story", "hitsPerPage": 30,
                          "numericFilters": f"created_at_i>{int(t0.timestamp())},created_at_i<{int(t1.timestamp())}"})
        for h in r.json().get("hits", []):
            out.append({"title": h.get("title") or "", "src": "Hacker News", "t": h["created_at_i"],
                        "link": h.get("url"), "points": h.get("points")})
    except Exception:
        pass
    time.sleep(1.0)
    cache[key] = out
    return out


def main():
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    stories = [s for s in json.load(open(os.path.join(D, "stories.json"), encoding="utf-8")) if s["n_ch"] >= MIN_CH]
    stories = stories[:LIMIT]
    cpath = os.path.join(D, "origins_cache.json")
    cache = json.load(open(cpath, encoding="utf-8")) if os.path.exists(cpath) else {}
    res = []
    for k, s in enumerate(stories, 1):
        t_first = datetime.fromisoformat(s["first_t"])
        t0, t1 = t_first - timedelta(days=3), t_first + timedelta(days=1)
        anc, lat, cyr = anchors(s["text"])
        if not anc:
            res.append({**s, "origin": None, "reason": "нет якорей"})
            continue
        found = []
        q_ru = " ".join(anc[:4])
        found += [dict(x, ed="ru") for x in gnews(q_ru, "ru", t0, t1, cache)]
        if len(lat) >= 1:
            q_en = " ".join(lat[:4])
            found += [dict(x, ed="en") for x in gnews(q_en, "en", t0, t1, cache)]
            found += [dict(x, ed="hn") for x in hn(" ".join(lat[:3]), t0, t1, cache)]
        if k % 10 == 0:
            json.dump(cache, open(cpath, "w", encoding="utf-8"), ensure_ascii=False)
        if not found:
            res.append({**s, "origin": None, "reason": "поиск пуст"})
            continue
        E = model.encode([s["text"]] + [f["title"] for f in found], normalize_embeddings=True, show_progress_bar=False)
        sims = E[1:] @ E[0]
        low = {a.lower() for a in anc}
        ok = []
        for f, sm in zip(found, sims):
            words = {w.lower() for w in re.findall(r"[\wА-Яа-яЁё.+-]{3,}", f["title"])}
            shared = any(a in words or any(a in w for w in words) for a in low)
            if sm >= MATCH_SIM and shared:
                ok.append(dict(f, sim=round(float(sm), 3)))
        ok.sort(key=lambda f: f["t"])
        if not ok:
            res.append({**s, "origin": None, "reason": "совпадений нет", "n_found": len(found)})
            continue
        wave = st.median([f["t"] for f in ok[:3]])
        res.append({**s, "origin": ok[0], "media_wave_t": wave, "n_matched": len(ok),
                    "first_ru": next((f for f in ok if f["ed"] == "ru"), None),
                    "first_en": next((f for f in ok if f["ed"] == "en"), None),
                    "first_hn": next((f for f in ok if f["ed"] == "hn"), None),
                    "lag_vs_first_min": round((t_first.timestamp() - ok[0]["t"]) / 60, 1),
                    "lag_vs_wave_min": round((t_first.timestamp() - wave) / 60, 1),
                    "matched": ok[:8]})
        if k % 25 == 0:
            print(f"  {k}/{len(stories)}", file=sys.stderr)
    json.dump(cache, open(cpath, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(res, open(os.path.join(D, "origins.json"), "w", encoding="utf-8"), ensure_ascii=False, default=str)
    m = [r for r in res if r.get("origin")]
    print(f"сюжетов {len(res)}, с внешним совпадением {len(m)}", file=sys.stderr)


if __name__ == "__main__":
    main()
