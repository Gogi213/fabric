"""Собирает docs/12-claims-registry.md из частей audit_parts/*.md и считает вердикты.

Запуск:  python tools/build_registry.py
"""
import os, re
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARTS = [
    ("04-sources-coverage.md", "Карта источников, реклама, полнота, происхождение новостей (docs/04, 08 §4, 06)"),
    ("02-03-05-crosspost.md", "Перепечатки, зарубежные каналы, скорость (docs/02, 03, 05)"),
    ("08-01-production-methodology.md", "Производство и методология (docs/08, 01, README)"),
    ("09-10-behaviour-stats.md", "Поведение и статистический аудит (docs/09, 10, README)"),
    ("07-06-market-gaps.md", "Рынок и пробелы (docs/07, 06, README)"),
]
CATS = ["доказано", "частично", "опровергнуто", "не доказано", "не проверяемо"]


def classify(cell):
    """Вердикт ячейки. Смешанные («ДОКАЗАНО (числа) / вывод ОПРОВЕРГНУТО») считаются частичными."""
    v = cell.upper().replace("*", "")
    nd = "НЕ ДОКАЗАНО" in v
    np_ = "НЕ ПРОВЕРЯЕМО" in v
    ref = "ОПРОВЕРГНУТО" in v
    part = "ЧАСТИЧНО" in v
    proved = "ДОКАЗАНО" in v.replace("НЕ ДОКАЗАНО", "")
    if part or (proved and (ref or nd)):
        return "частично"
    if ref:
        return "опровергнуто"
    if nd:
        return "не доказано"
    if np_:
        return "не проверяемо"
    if proved:
        return "доказано"
    return None


def verdicts(text):
    c = Counter()
    for line in text.splitlines():
        if not line.startswith("| ") or line.startswith("|---") or line.startswith("| ID"):
            continue
        cells = [x.strip() for x in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        k = classify(cells[3])
        if k:
            c[k] += 1
    return c


def main():
    blocks, rows = [], []
    total = Counter()
    for fn, title in PARTS:
        path = os.path.join(ROOT, "audit_parts", fn)
        if not os.path.exists(path):
            rows.append((title, None))
            continue
        text = open(path, encoding="utf-8").read()
        c = verdicts(text)
        total.update(c)
        rows.append((title, c))
        body = re.sub(r"^# .*\n", "", text, count=1)
        body = re.sub(r"^(#+) ", lambda m: "#" + m.group(1) + " ", body, flags=re.M)
        blocks.append(f"## {title}\n\n*Файл-источник: `audit_parts/{fn}`.*\n\n{body.strip()}\n")
    head = ["# 12. Реестр утверждений проекта: доказано / опровергнуто / переформулировано", "",
            "**Дата:** 2026-09-30  ·  **Сводка и выводы:** [`docs/11-recheck.md`](11-recheck.md)", "",
            "Каждое утверждение README и docs/01–10 проверено пересчётом из сырых данных или живой проверкой.",
            "Вердикты: **ДОКАЗАНО** — воспроизводится и выдерживает проверку; **ОПРОВЕРГНУТО** — данные "
            "говорят другое; **ЧАСТИЧНО** — число или часть вывода верны, формулировка нет (сюда же "
            "смешанные вердикты); **НЕ ДОКАЗАНО** — опора вывода не выдерживает, но и обратное не показано; "
            "**НЕ ПРОВЕРЯЕМО** — данных нет. Для всего, что не доказано, указано, что утверждать вместо "
            "и как это проверить.", "",
            "| Раздел | Доказано | Частично | Опровергнуто | Не доказано | Не проверяемо | Всего |",
            "|---|---|---|---|---|---|---|"]
    for title, c in rows:
        if c is None:
            head.append(f"| {title} | — | — | — | — | — | нет файла |")
            continue
        head.append("| " + title + " | " + " | ".join(str(c[k]) for k in CATS) + f" | {sum(c.values())} |")
    head.append("| **Итого** | " + " | ".join(f"**{total[k]}**" for k in CATS) + f" | **{sum(total.values())}** |")
    out = "\n".join(head) + "\n\n---\n\n" + "\n---\n\n".join(blocks)
    open(os.path.join(ROOT, "docs", "12-claims-registry.md"), "w", encoding="utf-8").write(out)
    print(dict(total), sum(total.values()))


if __name__ == "__main__":
    main()
