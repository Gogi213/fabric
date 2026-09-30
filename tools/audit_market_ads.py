"""audit_market_ads.py — кто реально рекламируется в 22 RU-каналах выборки.

Источник: data/links.json (2 недели, ссылки) + data/posts.json (неделя, текст).
Маркер рекламы: erid в тексте или ссылке (включая '&amp;erid='), либо «Реклама.»/
«Рекламодатель»/«ИНН» в тексте. Самоссылка канала с erid (t.me/<self>?erid=) учитывается
отдельно — это не сторонний рекламодатель.
Запуск: python tools/audit_market_ads.py
"""
import json, os, re
from collections import Counter, defaultdict
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
L = json.load(open(os.path.join(D, "links.json"), encoding="utf-8"))
SUBS = {k: v for k, v in json.load(open(os.path.join(D, "subs.json"), encoding="utf-8")).items()
        if not k.startswith("_")}
RU = list(SUBS)
MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
        "trends", "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]

RX_ERID = re.compile(r"erid[=:\s]*([A-Za-z0-9]{6,})", re.I)
RX_ADV = re.compile(r"(Рекламодатель|Реклама\.|ИНН\s*\d{8,})", re.I)
RX_ORG = re.compile(r"(?:Рекламодатель[:\s]*|Реклама\.\s*)((?:ООО|АО|ПАО|ИП|ТОО|МКПАО|НКО)?\s*[«\"]?[^\n,.;]{2,60})",
                    re.I)

# домен -> рекламодатель (ручная нормализация частых доменов)
DOM = [
    ("yandex", "Яндекс"), ("ya.ru", "Яндекс"), ("mts", "МТС"), ("mws", "МТС"),
    ("alfa", "Альфа-Банк"), ("sber", "Сбер"), ("tbank", "Т-Банк"), ("tinkoff", "Т-Банк"),
    ("t-bank", "Т-Банк"), ("vk.com", "VK"), ("vk.cc", "VK"), ("ozon", "Ozon"),
    ("wildberries", "Wildberries"), ("wb.ru", "Wildberries"), ("avito", "Авито"),
    ("beeline", "Билайн"), ("megafon", "МегаФон"), ("selectel", "Selectel"),
    ("skillbox", "Skillbox"), ("practicum", "Яндекс Практикум"), ("geekbrains", "GeekBrains"),
    ("netology", "Нетология"), ("otus", "OTUS"), ("x5", "X5"), ("kaspersky", "Касперский"),
    ("gosuslugi", "Госуслуги"), ("vtb", "ВТБ"), ("rt.ru", "Ростелеком"),
    ("rostelecom", "Ростелеком"), ("cloud.ru", "Cloud.ru"), ("timeweb", "Timeweb"),
    ("gazprom", "Газпром"), ("kion", "МТС"), ("okko", "Okko"), ("ivi", "ivi"),
]


def norm_dom(u):
    try:
        h = urlparse(u.replace("&amp;", "&")).netloc.lower()
    except Exception:
        return None
    h = h[4:] if h.startswith("www.") else h
    for k, v in DOM:
        if k in h:
            return v
    return h


rows = []
per_ch = Counter()
self_only = Counter()
adv_by_ch = defaultdict(Counter)
for ch in RU:
    for p in L.get(ch, []):
        links = [l.replace("&amp;", "&") for l in p.get("links", [])]
        text = p.get("text", "")
        erid_links = [l for l in links if RX_ERID.search(l)]
        third = [l for l in erid_links
                 if not re.match(r"https?://t\.me/%s\b" % re.escape(ch), l, re.I)]
        txt_erid = bool(RX_ERID.search(text))
        txt_adv = bool(RX_ADV.search(text))
        if not (erid_links or txt_erid or txt_adv):
            continue
        if erid_links and not third and not txt_erid and not txt_adv:
            self_only[ch] += 1
            continue
        per_ch[ch] += 1
        advs = set()
        for l in third:
            m = re.match(r"https?://t\.me/([A-Za-z0-9_]{4,})", l)
            advs.add(("@" + m.group(1).lower()) if m else norm_dom(l))
        mo = RX_ORG.search(text)
        if mo:
            advs.add("txt:" + mo.group(1).strip()[:40])
        if not advs:
            # erid без ссылки: берём первый внешний домен поста
            ext = [norm_dom(l) for l in links if "t.me/" not in l]
            advs.add(ext[0] if ext else "не определён")
        for a in advs:
            adv_by_ch[ch][a] += 1
        rows.append((ch, p["dt"][:10], sorted(advs), text[:120]))

print("маркированных постов (без самоссылок) у 22 RU-каналов за 2 недели:", len(rows))
print("постов только с самоссылкой-erid (исключены):", dict(self_only))
print("по каналам:", dict(per_ch))
allc = Counter()
for ch, c in adv_by_ch.items():
    for a, n in c.items():
        allc[a] += n
print("\nуникальных рекламодателей (грубо):", len(allc))
for a, n in allc.most_common(60):
    chs = [ch for ch in adv_by_ch if a in adv_by_ch[ch]]
    print(f"  {n:3d}  {a:45s} каналов={len(chs)} {chs[:6]}")

# грубая вертикаль
VERT = {
    "банк/финтех": ["Альфа", "Сбер", "Т-Банк", "ВТБ", "alfa", "bank", "банк"],
    "телеком/облака/IT-инфра": ["МТС", "Билайн", "МегаФон", "Selectel", "Ростелеком", "Cloud", "Timeweb", "mws"],
    "big tech / сервисы": ["Яндекс", "VK", "Ozon", "Авито", "Wildberries", "Okko", "ivi", "X5"],
    "образование": ["Практикум", "Skillbox", "GeekBrains", "Нетология", "OTUS", "school", "edu", "курс"],
}
vc = Counter()
for a, n in allc.items():
    v = "прочее"
    for k, keys in VERT.items():
        if any(x.lower() in a.lower() for x in keys):
            v = k
            break
    vc[v] += n
print("\nгрубые вертикали (посто-упоминания):", vc.most_common())
gamb = [a for a in allc if re.search(r"casino|bet|казино|ставк|1xbet|slot|gambl", a, re.I)]
print("gambling/betting среди рекламодателей:", gamb)
json.dump({"n_posts": len(rows), "self_only": self_only, "per_channel": per_ch,
           "advertisers": allc.most_common(), "verticals": vc.most_common(), "rows": rows},
          open(os.path.join(ROOT, "audit_parts", "audit_market_ads.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
