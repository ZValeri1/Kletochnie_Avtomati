"""Portable, offline trial reports; no server-side export files or dependencies."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from html import escape
from zipfile import ZIP_DEFLATED, ZipFile


METRICS = {
    "n_correct": "Атомы в узлах",
    "n_v": "Вакансии",
    "n_i": "Межузельные атомы",
    "n_as": "Атомы за контуром",
    "d": "Количество дефектов",
    "s": "Энтропия",
}
PARAMETERS = {
    "name": "Название", "simulation_count": "Экспериментов в сессии",
    "simulation_ids": "Эксперименты", "simulation_id": "ID эксперимента", "revision": "Ревизия",
    "dimensions": "Размеры металла", "field_dimensions": "Размеры поля",
    "contour": "Контур", "profile": "Профиль",
    "initialization_mode": "Режим инициализации",
    "n_v": "Начальные вакансии", "n_i": "Начальные межузельные атомы",
    "n_as": "Начальные атомы за контуром", "random_parameters": "Случайная инициализация",
    "seed_init": "Seed инициализации", "seed_sim": "Seed симуляции",
    "q_max_ev": "Максимальная энергия, эВ", "q_thr_ev": "Пороговая энергия, эВ",
    "weights": "Вероятности переходов",
    "external_direction_probabilities": "Направления внешних атомов",
    "repetitions": "Повторы", "steps": "Акты на запуск", "master_seed": "Master seed",
    "bootstrap_seed": "Bootstrap seed", "status": "Статус",
    "completed_steps": "Выполнено актов", "total_steps": "Запланировано актов",
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def _table(values):
    rows = []
    for key, value in values.items():
        rendered = _table(value) if isinstance(value, dict) else escape(_json(value))
        rows.append(f"<tr><th>{escape(PARAMETERS.get(key, key))}</th><td>{rendered}</td></tr>")
    return '<table class="parameters">' + "".join(rows) + "</table>"


def _chart(points, key, title):
    width, height = 760, 300
    left, top, plot_width, plot_height = 90, 30, 640, 215
    max_act = max(1, max((p["act_number"] for p in points), default=0))
    max_value = max(0.1 if key == "s" else 1, max((p[key] for p in points), default=0))
    def x(value):
        return left + value / max_act * plot_width
    def y(value):
        return top + plot_height - value / max_value * plot_height
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
             f'<title>{escape(title)}</title><rect width="100%" height="100%" fill="white"/>',
             '<g font-family="Arial,sans-serif" font-size="12" fill="#334155">']
    for i in range(5):
        value = max_value * i / 4
        parts.append(f'<line x1="{left}" x2="730" y1="{y(value):.3f}" y2="{y(value):.3f}" stroke="#e2e8f0"/>')
        parts.append(f'<text x="80" y="{y(value) + 4:.3f}" text-anchor="end">{value:.4g}</text>')
    for act in sorted({0, max_act // 2, max_act}):
        parts.append(f'<text x="{x(act):.3f}" y="265" text-anchor="middle">{act}</text>')
    parts.append('<path d="M90 30V245H730" fill="none" stroke="#64748b"/><text x="410" y="290" text-anchor="middle">Номер акта</text>')
    unit = "Энтропия S" if key == "s" else "Количество, шт."
    parts.append(f'<text transform="translate(18 138) rotate(-90)" text-anchor="middle">{unit}</text>')
    coordinates = " ".join(f'{x(p["act_number"]):.3f},{y(p[key]):.3f}' for p in points)
    parts.append(f'<polyline points="{coordinates}" fill="none" stroke="#2563eb" stroke-width="2"/>')
    for point in points:
        manual = point.get("origin") == "manual_edit"
        if manual or len(points) == 1:
            parts.append(f'<circle cx="{x(point["act_number"]):.3f}" cy="{y(point[key]):.3f}" r="3" fill="{"#d97706" if manual else "#2563eb"}"/>')
    if not points:
        parts.append('<text x="410" y="140" text-anchor="middle">Нет данных</text>')
    parts.append('</g></svg>')
    return "".join(parts)


def build_report(*, title, metadata, runs, failures=(), aggregate=None, configurations=()):
    """Runs contain captured configuration, full metrics and an immutable snapshot."""
    output = io.BytesIO()
    created_at = datetime.now(timezone.utc).isoformat()
    body = [f"<h1>{escape(title)}</h1>", f"<p>Создан: {created_at} (UTC)</p>", _table(metadata)]
    body.append('<p>Откройте report.html без подключения к серверу. Для PDF используйте печать браузера. '
                'SVG — отдельные графики, CSV — полный ряд метрик, JSON — исходные данные.</p>')
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("data.json", _json({"schema_version": 1, "created_at": created_at,
            "metadata": metadata, "configurations": configurations, "runs": runs,
            "failures": failures, "aggregate": aggregate}))
        if configurations:
            body.append("<h2>Заданные конфигурации серии</h2>")
            for index, configuration in enumerate(configurations):
                body.extend([f"<h3>Конфигурация {index + 1}</h3>", _table(configuration)])
        if not runs:
            body.append("<p>Нет завершённых запусков с результатами.</p>")
        for index, run in enumerate(runs):
            folder = f"runs/{index + 1:03d}"
            points = run["metrics"]
            name = run.get("name") or f'Испытание {run.get("run", index) + 1}'
            body.append(f'<section><h2>{escape(name)}</h2>')
            body.append(_table({key: run[key] for key in ("simulation_id", "configuration_index", "revision", "status") if key in run}))
            archive.writestr(f"{folder}/metadata.json", _json({"name": name, "simulation_id": run.get("simulation_id")}))
            body.extend(["<h3>Начальные параметры</h3>", _table(run["configuration"])])
            body.append('<p>Параметры инициализации заданы до расчёта; ручные правки отмечены оранжевым. '
                        'D = N_V + N_I + N_As; S = −Σ pᵢ ln(pᵢ), безразмерная величина.</p>')
            if points:
                initial = next((p for p in reversed(points) if p["act_number"] == 0), points[0])
                body.append("<h3>Начальные и итоговые метрики</h3><table><tr><th>Метрика</th><th>Начало</th><th>Итог</th></tr>")
                for key, label in METRICS.items():
                    body.append(f"<tr><th>{label}</th><td>{initial[key]}</td><td>{points[-1][key]}</td></tr>")
                body.append("</table>")
            archive.writestr(f"{folder}/parameters.json", _json(run["configuration"]))
            csv_buffer = io.StringIO(newline="")
            writer = csv.DictWriter(csv_buffer, fieldnames=["revision", "act_number", "origin", *METRICS], extrasaction="ignore")
            writer.writeheader()
            writer.writerows(points)
            archive.writestr(f"{folder}/metrics.csv", csv_buffer.getvalue().encode("utf-8-sig"))
            body.append('<div class="charts">')
            for key, label in METRICS.items():
                svg = _chart(points, key, f"{name}: {label}")
                archive.writestr(f"{folder}/{key}.svg", svg)
                body.append(f"<figure><figcaption>{label}</figcaption>{svg}</figure>")
            body.append("</div></section>")
        if aggregate:
            body.append("<h2>Сводные результаты серии</h2><p>Средние по завершённым запускам; без заполнения отсутствующих актов нулями.</p>")
            body.append('<div class="charts">')
            for key, label in METRICS.items():
                points = [{"act_number": int(act), key: values[key]["mean"]}
                          for act, values in sorted(aggregate["by_act"].items(), key=lambda item: int(item[0])) if key in values]
                svg = _chart(points, key, f"Среднее: {label}")
                archive.writestr(f"aggregate/{key}.svg", svg)
                body.append(f"<figure><figcaption>Среднее: {label}</figcaption>{svg}</figure>")
            body.append("</div><h3>Финальные агрегаты</h3><table><tr><th>Метрика</th><th>N</th><th>Среднее</th><th>min…max</th><th>p50 / p95</th><th>95% CI</th></tr>")
            for key, value in aggregate["final"].items():
                low, high = value["confidence_interval"]
                note = " (неинформативен)" if not value["ci_informative"] else ""
                body.append(f'<tr><th>{escape(METRICS.get(key, key))}</th><td>{value["count"]}</td><td>{value["mean"]:.6g}</td><td>{value["minimum"]:.6g}…{value["maximum"]:.6g}</td><td>{value["p50"]:.6g} / {value["p95"]:.6g}</td><td>{low:.6g}…{high:.6g}{note}</td></tr>')
            body.append("</table>")
        if failures:
            body.append("<h2>Ошибки запусков</h2>")
            for failure in failures:
                body.append(_table(failure))
        if metadata.get("status") == "CANCELLED":
            body.append("<p>Серия отменена. В отчёте только завершённые запуски; незавершённые не включены в графики и агрегаты.</p>")
        html = '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        html += f"<title>{escape(title)}</title><style>"
        html += 'body{font:15px/1.5 Arial,sans-serif;color:#172033;background:#fff;max-width:1200px;margin:32px auto;padding:0 24px}h1,h2,h3{color:#153b68}h2{border-bottom:2px solid #dbeafe;padding-bottom:8px;margin-top:36px}table{border-collapse:collapse;width:100%;margin:12px 0;overflow-wrap:anywhere}th,td{border:1px solid #cbd5e1;padding:7px;text-align:left;vertical-align:top}th{background:#f1f5f9}td table{margin:0}figure{margin:0;break-inside:avoid}figcaption{font-weight:bold;margin-top:16px}svg{width:100%;height:auto}.charts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}@media(max-width:800px){.charts{grid-template-columns:1fr}}@media print{body{margin:0;padding:0;font-size:10pt}.charts{display:block}figure{margin-bottom:16px}h2,h3{break-after:avoid}tr{break-inside:avoid}}'
        html += "</style><body>" + "".join(body) + "</body></html>"
        archive.writestr("report.html", html)
    return output.getvalue()
