"""
HTML-дашборд отчёта — генерируется КОДОМ строго из валидированных JSON-отчётов.

Зачем именно код, а не агент: если верстать отчёт «руками» в LLM, картинка может
разойтись с данными (или быть сочинённой целиком). Этот модуль рендерит дашборд только
из того, что реально лежит в `reports/<host>/*.json`, прогнав каждый файл через страж
(`agent/validate`). Сочинённые отчёты в дашборд не попадают — выносятся в баннер.

Markdown-версия для чата с агентом — `agent/summary.py` (build_summary). Так у продакта
два варианта: открыть `report.html` в браузере или читать `SUMMARY.md` прямо в чате.

Использование:
    python -m agent.report_html reports/bitrix.carrotquest.ru
    python -m agent.report_html reports/bitrix.carrotquest.ru --out reports/bitrix.carrotquest.ru/report.html
"""

import argparse
import html
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

from .summary import _load_reports, build_summary
from .validate import validate_report, VALID, NO_USER_ID, FABRICATED

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:#0f172a;color:#f8fafc;
  line-height:1.6;padding:2rem;min-height:100vh;
  background-image:radial-gradient(at 0% 0%,rgba(255,107,53,.15) 0,transparent 50%),
  radial-gradient(at 100% 100%,rgba(16,185,129,.1) 0,transparent 50%);background-attachment:fixed}
.container{max-width:1200px;margin:0 auto}
header{margin-bottom:2.5rem;text-align:center}
h1{font-size:2.4rem;font-weight:700;background:linear-gradient(to right,#ff8a5c,#ffb347);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:.4rem}
.subtitle{color:#94a3b8;font-size:1.05rem}
.subtitle code{color:#cbd5e1}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:1.3rem;margin-bottom:2.5rem}
.card{background:rgba(30,41,59,.7);backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.1);
  border-radius:1rem;padding:1.4rem;text-align:center}
.card-title{font-size:.82rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.4rem}
.card-value{font-size:2.4rem;font-weight:700}
.v-ok{color:#10b981}.v-bad{color:#ef4444}.v-warn{color:#f59e0b}
.banner{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.35);border-radius:.75rem;
  padding:1rem 1.3rem;margin-bottom:2rem;color:#fca5a5}
.box{background:rgba(30,41,59,.8);border-left:4px solid #ff6b35;border-radius:.5rem;
  padding:1.3rem 1.7rem;margin-bottom:2.5rem}
.box h3{color:#fff;margin-bottom:.8rem;font-size:1.2rem}
.box p,.box li{color:#94a3b8;margin-bottom:.7rem}.box ul{margin-left:1.4rem}.box strong{color:#fff}
.section-title{font-size:1.4rem;margin-bottom:1.2rem;border-bottom:1px solid rgba(255,255,255,.1);padding-bottom:.5rem}
.tw{background:rgba(30,41,59,.7);border:1px solid rgba(255,255,255,.1);border-radius:1rem;overflow:hidden;margin-bottom:2.5rem}
table{width:100%;border-collapse:collapse}
th,td{padding:.9rem 1.3rem;text-align:left;border-bottom:1px solid rgba(255,255,255,.1)}
th{background:rgba(0,0,0,.2);font-weight:600;color:#94a3b8;text-transform:uppercase;font-size:.8rem;letter-spacing:.05em}
tr:last-child td{border-bottom:none}tr:hover td{background:rgba(255,255,255,.02)}
.badge{display:inline-flex;align-items:center;padding:.2rem .7rem;border-radius:9999px;font-size:.82rem;font-weight:500;gap:.4rem}
.b-ok{background:rgba(16,185,129,.1);color:#10b981;border:1px solid rgba(16,185,129,.2)}
.b-bad{background:rgba(239,68,68,.1);color:#ef4444;border:1px solid rgba(239,68,68,.2)}
.b-warn{background:rgba(245,158,11,.1);color:#f59e0b;border:1px solid rgba(245,158,11,.2)}
.b-mut{background:rgba(148,163,184,.1);color:#94a3b8;border:1px solid rgba(148,163,184,.2)}
a.link{color:#ff8a5c;text-decoration:none;font-weight:500;font-size:.9rem}a.link:hover{text-decoration:underline}
.bugs{display:grid;grid-template-columns:1fr 1fr;gap:1.6rem}
.bug-card{background:rgba(30,41,59,.7);border:1px solid rgba(255,255,255,.1);border-radius:1rem;padding:1.4rem}
.bug-card h3{margin-bottom:1rem;display:flex;align-items:center;gap:.5rem}
.bug-list{list-style:none}
.bug-list li{padding:.9rem;background:rgba(0,0,0,.2);border-radius:.5rem;margin-bottom:.5rem;border-left:4px solid transparent}
.bug-list li.dom{border-left-color:#ef4444}.bug-list li.api{border-left-color:#f59e0b}
.bug-desc{font-weight:500;margin-bottom:.2rem}.bug-meta{font-size:.85rem;color:#94a3b8}
footer{text-align:center;color:#64748b;font-size:.82rem;margin-top:2.5rem}
@media(max-width:768px){.bugs{grid-template-columns:1fr}.tw{overflow-x:auto}}
"""


def _esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def build_html(reports: list[dict]) -> str:
    """Рендерит дашборд из списка отчётов. Сочинённые отсеивает в баннер."""
    verdicts = {id(r): validate_report(r)[0] for r in reports}
    good = [r for r in reports if verdicts[id(r)] != FABRICATED]
    fabricated = [r for r in reports if verdicts[id(r)] == FABRICATED]
    good = sorted(good, key=lambda r: r.get("started_at", ""))

    site = next((r.get("site_url") for r in good if r.get("site_url")), "—")
    date = (good[0].get("started_at", "") or "")[:10] if good else ""

    total = len(good)
    n_valid = sum(1 for r in good if verdicts[id(r)] == VALID)
    dom_total = sum(r.get("bug_count", 0) for r in good)
    api_total = sum(1 for r in good if r.get("send_bugs"))

    def has_send(r):
        return bool(r.get("send_bugs"))

    # --- summary cards ---
    cards = [
        ("Всего сценариев", str(total), ""),
        ("Валидных", str(n_valid), "v-ok"),
        ("DOM-наложения", str(dom_total), "v-bad" if dom_total else "v-ok"),
        ("Сигналы API", str(api_total), "v-warn" if api_total else "v-ok"),
    ]
    if fabricated:
        cards.append(("Фабрикаций", str(len(fabricated)), "v-bad"))
    cards_html = "".join(
        f'<div class="card"><div class="card-title">{_esc(t)}</div>'
        f'<div class="card-value {c}">{_esc(v)}</div></div>'
        for t, v, c in cards
    )

    banner = ""
    if fabricated:
        bad = ", ".join(_esc(r.get("scenario_id") or "—") for r in fabricated)
        banner = (
            f'<div class="banner">❌ <strong>Обнаружена фабрикация:</strong> '
            f'{len(fabricated)} отчётов не являются выводом реального прогона ({bad}). '
            f'Они исключены из дашборда. Нужен честный перепрогон через '
            f'<code>python -m agent.run_suite</code>.</div>'
        )

    # --- unique bugs (DOM + API) ---
    dom_key, dom_ex = Counter(), {}
    send_key, send_ex = Counter(), {}
    for r in good:
        for b in r.get("bugs", []):
            k = (b.get("type"), tuple(sorted(b.get("popups_involved", []))))
            dom_key[k] += 1
            dom_ex.setdefault(k, b)
        for b in r.get("send_bugs", []):
            k = (b.get("type"), tuple(sorted(b.get("popups", []))))
            send_key[k] += 1
            send_ex.setdefault(k, b)

    # --- conclusions ---
    concl = ["<div class=\"box\"><h3>Выводы и анализ</h3>",
             f"<p>Прогнано <strong>{total}</strong> сценариев. "]
    if not dom_key and not send_key:
        concl.append("Проблем не обнаружено — все попапы отрабатывали корректно.</p>")
    else:
        concl.append("Найдены проблемы:</p><ul>")
        for (btype, popups), cnt in dom_key.most_common():
            name = "Наложение попапов" if btype == "overlap" else "Быстрое повторное появление"
            concl.append(
                f'<li><strong style="color:#ef4444">DOM — {_esc(name)}:</strong> '
                f'{_esc(", ".join(popups))} · в {cnt} сценариях.</li>'
            )
        for (btype, popups), cnt in send_key.most_common():
            name = "Одновременная отправка" if btype == "send_concurrent" else "Повторная отправка"
            concl.append(
                f'<li><strong style="color:#f59e0b">API — {_esc(name)} (тайминги CQ):</strong> '
                f'{_esc(", ".join(popups))} · в {cnt} сценариях. Признак ошибки в конфигурации '
                f'триггеров кампаний даже без визуального наложения.</li>'
            )
        concl.append("</ul><p><strong>Рекомендация:</strong> проверить задержки и условия "
                     "показа конфликтующих кампаний в админке Carrot Quest.</p>")
    concl.append("</div>")
    concl_html = "".join(concl)

    # --- per-scenario table ---
    rows = []
    for r in good:
        sid = _esc(r.get("scenario_id") or "—")
        dur = f'{r.get("duration_sec", 0)} c'
        v = verdicts[id(r)]
        bc = r.get("bug_count", 0)
        if v == NO_USER_ID:
            dom_cell = '<span class="badge b-mut">⚠️ нет user_id</span>'
        elif bc:
            dom_cell = f'<span class="badge b-bad">🔴 {bc}</span>'
        else:
            dom_cell = '<span class="badge b-ok">✅ 0</span>'
        sb = len(r.get("send_bugs", []))
        api_cell = f'<span class="badge b-warn">🟠 {sb}</span>' if sb else '<span class="badge b-mut">—</span>'
        if r.get("card_url"):
            link = f'<a class="link" href="{_esc(r["card_url"])}" target="_blank">Открыть профиль →</a>'
        else:
            link = '<span class="badge b-mut">—</span>'
        rows.append(
            f"<tr><td><strong>{sid}</strong></td><td>{_esc(dur)}</td>"
            f"<td>{dom_cell}</td><td>{api_cell}</td><td>{link}</td></tr>"
        )
    table_html = (
        '<h2 class="section-title">Результаты по сценариям</h2><div class="tw"><table>'
        '<thead><tr><th>Сценарий</th><th>Длит.</th><th>DOM-баги</th>'
        '<th>Сигнал отправки</th><th>Профиль Carrot Quest</th></tr></thead><tbody>'
        + "".join(rows) + "</tbody></table></div>"
    )

    # --- bug detail cards ---
    dom_items = "".join(
        f'<li class="dom"><div class="bug-desc">{_esc(", ".join(popups))}</div>'
        f'<div class="bug-meta">{"Наложение" if btype=="overlap" else "Быстрое повторение"} · '
        f'воспроизведено в {cnt} сценариях</div></li>'
        for (btype, popups), cnt in dom_key.most_common()
    ) or '<li class="bug-meta">DOM-наложений не обнаружено.</li>'
    send_items = "".join(
        f'<li class="api"><div class="bug-desc">{_esc(", ".join(popups))}</div>'
        f'<div class="bug-meta">{"Одновременная отправка" if btype=="send_concurrent" else "Повторная отправка"} · '
        f'в {cnt} сценариях</div></li>'
        for (btype, popups), cnt in send_key.most_common()
    ) or '<li class="bug-meta">Сигналов по таймингам отправки нет.</li>'
    bugs_html = (
        '<h2 class="section-title">Подробная сводка по багам</h2><div class="bugs">'
        f'<div class="bug-card"><h3 style="color:#ef4444">🔴 DOM-наложения</h3>'
        f'<ul class="bug-list">{dom_items}</ul></div>'
        f'<div class="bug-card"><h3 style="color:#f59e0b">🟠 Сигналы API (тайминги)</h3>'
        f'<ul class="bug-list">{send_items}</ul></div></div>'
    )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Отчёт тестирования попапов: {_esc(site)}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head>
<body>
<div class="container">
<header>
<h1>Отчёт тестирования попапов</h1>
<p class="subtitle">Сайт: <code>{_esc(site)}</code> &nbsp;|&nbsp; Дата: {_esc(date)}</p>
</header>
{banner}
<div class="cards">{cards_html}</div>
{concl_html}
{table_html}
{bugs_html}
<footer>Mosh · CQ Popup QA Agent · отчёт сгенерирован кодом из валидированных JSON</footer>
</div>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="HTML-дашборд отчёта из валидированных JSON")
    parser.add_argument("folder", help="Папка с JSON-отчётами (например reports/bitrix.carrotquest.ru)")
    parser.add_argument("--out", default=None, help="Куда сохранить HTML (по умолчанию <folder>/report.html)")
    args = parser.parse_args()

    reports = _load_reports(args.folder)
    if not reports:
        print(f"❌ В {args.folder} нет отчётов — нечего рендерить.")
        sys.exit(1)

    out = args.out or os.path.join(args.folder, "report.html")
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(build_html(reports))
    print(f"[html] Дашборд сохранён: {out}")

    # Markdown-версия для чата — чтобы у продакта были оба варианта.
    md = os.path.join(args.folder, "SUMMARY.md")
    if not os.path.exists(md):
        with open(md, "w", encoding="utf-8") as f:
            f.write(build_summary(reports))
        print(f"[md] Markdown-сводка для чата: {md}")
    else:
        print(f"[md] Markdown-сводка для чата уже есть: {md}")


if __name__ == "__main__":
    main()
