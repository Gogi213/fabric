"""R6. Рекламодатели по отраслям и размерам каналов.

Рекламный пост = явная маркировка (r_lib.is_marked_ad). Адрес назначения — раскрытая ссылка
(data/r/ad_url_resolved.json), иначе домен ссылки. Отрасль — по домену (правила ниже).
Скидочные партнёрские каналы (доля ссылок на маркетплейсы ≥ 30 %) считаются отдельно: это модель
«заработок на партнёрке», а не продажа рекламы.
"""
import json, os, re, statistics as st, sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT, advertiser, is_marked_ad, load  # noqa: E402

D = os.path.join(ROOT, "data", "r")
RES = json.load(open(os.path.join(D, "ad_url_resolved.json"), encoding="utf-8"))
CH = {c["handle"]: c for c in json.load(open(os.path.join(D, "channels.json"), encoding="utf-8"))}
SECTORS = [
    ("Маркетплейсы и ритейл", r"aliexpress|ozon|wildberries|wb\.ru|market\.yandex|citilink|mvideo|eldorado|cifrus|dns-shop|avito|ergostol|lamoda|megamarket|sbermegamarket|yandex\.ru/market"),
    ("Облака и IT-инфраструктура", r"selectel|mws\.ru|yandex\.cloud|cloud\.ru|timeweb|beget|reg\.ru|vk\.cloud|cloud\.vk|servers\.ru|rusonyx|firstvds|hostkey"),
    ("Онлайн-школы и курсы", r"otus|practicum|karpov|eduson|synergy|newprolab|codeby|skillbox|geekbrains|netology|skillfactory|hexlet|stepik|productstar|kursy|academy|courses|school|education"),
    ("IT-мероприятия", r"techday|digitalday|pt-event|heisenbug|jokerconf|yace|deeptechnight|conf|summit|forum|meetup|holyjs|highload|podlodka|cybercamp|jetcsirt"),
    ("Банки и финтех", r"alfa|sber|tbank|tinkoff|vtb|gazprombank|raiffeisen|psbank|ozonbank|yoomoney|qiwi|bank"),
    ("Телеком", r"mts\.ru|beeline|megafon|t2\.ru|tele2|rostelecom|yota"),
    ("Кибербез-вендоры", r"kaspersky|securityvision|ptsecurity|positive|kontur|infowatch|solar|bi\.zone|securitycode|usergate"),
    ("Видео и медиа (самопромо)", r"youtube|vkvideo|rutube|teletype|dzen|securitylab|habr"),
    ("ИИ-сервисы и боты", r"gpt|ai\.|neuro|bot|nano|midjourney|syntx|chatgpt"),
]


def sector(host):
    for name, rx in SECTORS:
        if re.search(rx, host or ""):
            return name
    return "Прочее"


def band(s):
    return "?" if not s else "<10K" if s < 1e4 else "10–50K" if s < 5e4 else "50–200K" if s < 2e5 else "200K–1M" if s < 1e6 else "1M+"


C = load()
rows = []
for ch, d in C.items():
    info = CH.get(ch, {})
    deal = (info.get("deal_share") or 0) >= 0.3
    for p in d["posts"]:
        if not is_marked_ad(p):
            continue
        hosts = []
        for u, _ in p.get("links") or []:
            u2 = u.replace("&amp;", "&")
            h = (RES.get(u2) or {}).get("final_host") or urlparse(u2).netloc.lower()
            if h and "t.me" not in h and "telegram" not in h:
                hosts.append(h.removeprefix("www."))
        name, inn = advertiser(p)
        host = hosts[0] if hosts else None
        rows.append({"ch": ch, "subs": info.get("subs"), "kind": info.get("kind"), "deal_channel": deal,
                     "host": host, "sector": sector(host) if host else ("Telegram-канал/бот" if p.get("links") else "без ссылки"),
                     "advertiser": name, "inn": inn, "views": p.get("views")})

reg = [r for r in rows if not r["deal_channel"]]
print(f"маркированных рекламных постов {len(rows)}; из них в скидочных партнёрских каналах "
      f"{sum(r['deal_channel'] for r in rows)} ({len({r['ch'] for r in rows if r['deal_channel']})} каналов)")
print(f"\nОбычная реклама (без скидочных каналов): {len(reg)} постов в {len({r['ch'] for r in reg})} каналах")
sec = Counter(r["sector"] for r in reg)
sec_ch = defaultdict(set)
for r in reg:
    sec_ch[r["sector"]].add(r["ch"])
for s, n in sec.most_common():
    print(f"  {s:32s} постов {n:4d}  каналов {len(sec_ch[s]):3d}")
print("\nЧастые рекламодатели (по конечному домену, без скидочных каналов):")
adv = defaultdict(lambda: {"posts": 0, "ch": set(), "bands": Counter()})
for r in reg:
    k = r["host"] or (r["advertiser"] or "?")
    adv[k]["posts"] += 1
    adv[k]["ch"].add(r["ch"])
    adv[k]["bands"][band(r["subs"])] += 1
top = sorted(adv.items(), key=lambda x: (-len(x[1]["ch"]), -x[1]["posts"]))
for k, a in top[:35]:
    print(f"  {k[:34]:34s} {sector(k)[:24]:24s} постов {a['posts']:3d} каналов {len(a['ch']):3d}  {dict(a['bands'])}")
print("\nГде покупают: доля каналов с ≥1 рекламой и медиана рекламных постов за 14 дней (медиа-каналы)")
MEDIA = {"Медиа: AI и тех-новости", "Медиа: массовые тех-развлекательные", "Медиа: гаджеты и железо",
         "Apple и смартфоны (медиа и магазины)", "Медиа: кибербез и мошенничество"}
for b in ["10–50K", "50–200K", "200K–1M", "1M+"]:
    chs = [h for h, c in CH.items() if c.get("kind") in MEDIA and band(c.get("subs")) == b]
    n_ads = [sum(1 for r in reg if r["ch"] == h) for h in chs]
    if chs:
        print(f"  {b:8s} медиа {len(chs):3d}  с рекламой {sum(1 for x in n_ads if x):3d} ({100*sum(1 for x in n_ads if x)/len(chs):3.0f} %)  "
              f"рекламных постов на канал с рекламой: медиана {st.median([x for x in n_ads if x]) if any(n_ads) else 0}")
json.dump({"rows": rows, "sectors": sec.most_common(),
           "top_advertisers": [{"key": k, "sector": sector(k), "posts": a["posts"], "channels": sorted(a["ch"]),
                                "bands": dict(a["bands"])} for k, a in top[:100]]},
          open(os.path.join(D, "r6_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
