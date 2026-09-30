import json
d = json.load(open("cross_strict.json", encoding="utf-8"))

def show(pred, label):
    print("=" * 100)
    print(label)
    print("=" * 100)
    for h in d:
        if not pred(h):
            continue
        g = h["gap_min"]
        lead = "RU первым" if g < 0 else "EN первым"
        print(f"  sim={h['sim']:.3f}  {lead} на {abs(g):5.0f} мин")
        print(f"    EN {h['en_ch']:16s} {h['en_dt'][5:16]}  {h['en_text'][:100]}")
        print(f"    RU {h['ru_ch']:16s} {h['ru_dt'][5:16]}  {h['ru_text'][:100]}")
        if h["ru_fwd"]:
            print(f"       атрибуция RU: {h['ru_fwd']}")

show(lambda h: h["en_ch"] == "AInews_en", "@AInews_en vs русские")
show(lambda h: h["en_ch"] in ("GitHub", "news_crypto"),
     "@GitHub / @news_crypto -> русские (EN первым)")
show(lambda h: h["en_ch"] == "aipost" and h["gap_min"] > 0,
     "@aipost -> русские (EN первым)")
