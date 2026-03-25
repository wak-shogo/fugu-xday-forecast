#!/usr/bin/env python3
import argparse
import html
import json
import math
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "predictions.json"

MANEIMARU_HOME = "https://www.maneimaru.jp/"
MANEIMARU_PAGE_API = "https://www.maneimaru.jp/api/getTopDataListPage/"
LATITUDE = 35.114
LONGITUDE = 139.835
TIMEZONE_NAME = "Asia/Tokyo"
SYNODIC_MONTH = 29.53058867
REFERENCE_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
FEATURE_KEYS = ("airTemp", "seaTemp", "moonAge")
FEATURE_TERMS = [
    "intercept",
    "airTemp",
    "seaTemp",
    "moonAge",
    "airTemp*seaTemp",
    "airTemp*moonAge",
    "seaTemp*moonAge",
    "airTemp^2",
    "seaTemp^2",
    "moonAge^2",
]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--today", type=str, default=None)
    return parser.parse_args()


def fetch_text(url, params=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", "ignore")


def fetch_json(url, params=None):
    return json.loads(fetch_text(url, params))


def clean_fragment(raw):
    plain = re.sub(r"<[^>]+>", "", raw)
    plain = html.unescape(plain)
    return re.sub(r"\s+", " ", plain.replace("\u3000", " ")).strip()


def parse_count(text):
    range_match = re.search(r"(\d+(?:\.\d+)?)\s*[-〜~]\s*(\d+(?:\.\d+)?)\s*匹", text)
    if range_match:
        return float(range_match.group(1)), float(range_match.group(2))
    single_match = re.search(r"(\d+(?:\.\d+)?)\s*匹", text)
    if single_match:
        value = float(single_match.group(1))
        return value, value
    return None


def parse_posts(page_html):
    posts = []
    for block in re.split(r'<div class="blog">', page_html)[1:]:
        date_match = re.search(r'<h2 class="date">(\d{4}年\d{2}月\d{2}日)</h2>', block)
        title_match = re.search(r'<h3 class="title"><a href="([^"]+)"[^>]*>([^<]+)</a>', block)
        fish_match = re.search(r'<span class="fish-name">([^<]+)</span>', block)
        fish_num_match = re.search(r'<span class="fish-num">(.*?)</span>', block, re.S)
        posted_match = re.search(r'<div class="posted">(?:posted by [^<]+ )?at? ?(\d{1,2}:\d{2})', block)
        if not (date_match and title_match and fish_match and fish_num_match):
            continue

        fish_name = clean_fragment(fish_match.group(1))
        title = clean_fragment(title_match.group(2))
        if "トラフグ" not in fish_name and "トラフグ" not in title:
            continue

        fish_num = clean_fragment(fish_num_match.group(1))
        parsed_count = parse_count(fish_num)
        if not parsed_count:
            continue

        posts.append(
            {
                "date": datetime.strptime(date_match.group(1), "%Y年%m月%d日").date(),
                "title": title,
                "url": urllib.parse.urljoin(MANEIMARU_HOME, title_match.group(1)),
                "fishName": fish_name,
                "fishNum": fish_num,
                "catchMin": parsed_count[0],
                "catchMax": parsed_count[1],
                "postedAt": posted_match.group(1) if posted_match else None,
            }
        )
    return posts


def extract_page_dates(page_html):
    return [datetime.strptime(raw, "%Y年%m月%d日").date() for raw in re.findall(r'<h2 class="date">(\d{4}年\d{2}月\d{2}日)</h2>', page_html)]


def collect_daily_results(oldest_keep_date=None):
    daily = {}
    seen_urls = set()
    for page in range(1, 121):
        html_text = fetch_text(MANEIMARU_HOME) if page == 1 else fetch_text(MANEIMARU_PAGE_API, {"p": page})
        stripped = html_text.strip()
        if not stripped or stripped.startswith("nodata"):
            break
        page_dates = extract_page_dates(html_text)
        page_posts = parse_posts(html_text)
        if not page_posts:
            if oldest_keep_date and page_dates and min(page_dates) < oldest_keep_date:
                break
            continue
        for post in page_posts:
            if post["url"] in seen_urls:
                continue
            seen_urls.add(post["url"])
            key = post["date"].isoformat()
            current = daily.get(key)
            if not current:
                daily[key] = post
                continue
            current["catchMin"] = min(current["catchMin"], post["catchMin"])
            current["catchMax"] = max(current["catchMax"], post["catchMax"])
            current["fishNum"] = post["fishNum"]
            current["url"] = post["url"]
        if oldest_keep_date and page_dates and min(page_dates) < oldest_keep_date:
            break
    return [daily[key] for key in sorted(daily.keys())]


def fetch_open_meteo_daily(base_url, start_date, end_date, fields):
    payload = fetch_json(
        base_url,
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "timezone": TIMEZONE_NAME,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": ",".join(fields),
        },
    )
    daily = payload["daily"]
    output = {}
    for index, day in enumerate(daily["time"]):
        output[day] = {field: daily[field][index] for field in fields}
    return output


def combine_feature_sources(air_map, sea_map):
    combined = {}
    for day, values in air_map.items():
        combined.setdefault(day, {}).update(values)
    for day, values in sea_map.items():
        combined.setdefault(day, {}).update(values)
    return combined


def moon_age_for(day):
    instant = datetime.combine(day, time(hour=12), tzinfo=timezone.utc)
    delta_days = (instant - REFERENCE_NEW_MOON).total_seconds() / 86400.0
    return delta_days % SYNODIC_MONTH


def quantile(values, q):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def clamp(value, lower, upper):
    return max(lower, min(upper, value))


def circular_distance(day_a, day_b, span=366):
    delta = abs(day_a - day_b)
    return min(delta, span - delta)


def build_climatology(feature_map):
    buckets = {}
    for iso, values in feature_map.items():
        air = values.get("temperature_2m_mean")
        sea = values.get("sea_surface_temperature_mean")
        if air is None or sea is None:
            continue
        day = date.fromisoformat(iso)
        doy = day.timetuple().tm_yday
        bucket = buckets.setdefault(doy, {"temperature_2m_mean": [], "sea_surface_temperature_mean": []})
        bucket["temperature_2m_mean"].append(air)
        bucket["sea_surface_temperature_mean"].append(sea)

    global_air = [value for bucket in buckets.values() for value in bucket["temperature_2m_mean"]]
    global_sea = [value for bucket in buckets.values() for value in bucket["sea_surface_temperature_mean"]]

    climatology = {}
    for doy in range(1, 367):
        radius = 6
        air_values = []
        sea_values = []
        while radius <= 45 and (not air_values or not sea_values):
            air_values = []
            sea_values = []
            for other_doy, values in buckets.items():
                if circular_distance(doy, other_doy) <= radius:
                    air_values.extend(values["temperature_2m_mean"])
                    sea_values.extend(values["sea_surface_temperature_mean"])
            radius += 6
        climatology[doy] = {
            "temperature_2m_mean": sum(air_values or global_air) / len(air_values or global_air),
            "sea_surface_temperature_mean": sum(sea_values or global_sea) / len(sea_values or global_sea),
        }
    return climatology


def resolve_feature(day, archive_map, forecast_map, climatology):
    iso = day.isoformat()
    baseline = climatology[day.timetuple().tm_yday]
    if iso in archive_map:
        record = dict(baseline)
        record.update({key: value for key, value in archive_map[iso].items() if value is not None})
        return record, "archive"
    if iso in forecast_map:
        record = dict(baseline)
        record.update({key: value for key, value in forecast_map[iso].items() if value is not None})
        return record, "forecast"
    return dict(baseline), "climatology"


def round_half(value):
    return round(value * 2) / 2.0


def round_feature_range(values, lower_pad=0.0, upper_pad=0.0):
    low = min(values) - lower_pad
    high = max(values) + upper_pad
    return round_half(low), round_half(high)


def compute_base_stats(rows):
    stats = {"means": {}, "scales": {}}
    for key in FEATURE_KEYS:
        values = [row[key] for row in rows]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        stats["means"][key] = mean
        stats["scales"][key] = math.sqrt(variance) or 1.0
    return stats


def build_basis(raw_features, stats):
    air = (raw_features["airTemp"] - stats["means"]["airTemp"]) / stats["scales"]["airTemp"]
    sea = (raw_features["seaTemp"] - stats["means"]["seaTemp"]) / stats["scales"]["seaTemp"]
    moon = (raw_features["moonAge"] - stats["means"]["moonAge"]) / stats["scales"]["moonAge"]
    return [
        1.0,
        air,
        sea,
        moon,
        air * sea,
        air * moon,
        sea * moon,
        air * air,
        sea * sea,
        moon * moon,
    ]


def solve_linear_system(matrix, vector):
    size = len(vector)
    augmented = [row[:] + [value] for row, value in zip(matrix, vector)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-9:
            augmented[pivot][col] = 1e-9
        if pivot != col:
            augmented[col], augmented[pivot] = augmented[pivot], augmented[col]

        pivot_value = augmented[col][col]
        for j in range(col, size + 1):
            augmented[col][j] /= pivot_value

        for row in range(size):
            if row == col:
                continue
            factor = augmented[row][col]
            if factor == 0:
                continue
            for j in range(col, size + 1):
                augmented[row][j] -= factor * augmented[col][j]

    return [augmented[row][size] for row in range(size)]


def fit_ridge_regression(design_matrix, targets, ridge):
    feature_count = len(design_matrix[0])
    gram = [[0.0 for _ in range(feature_count)] for _ in range(feature_count)]
    rhs = [0.0 for _ in range(feature_count)]

    for features, target in zip(design_matrix, targets):
        for i in range(feature_count):
            rhs[i] += features[i] * target
            for j in range(feature_count):
                gram[i][j] += features[i] * features[j]

    for index in range(1, feature_count):
        gram[index][index] += ridge

    return solve_linear_system(gram, rhs)


def clip_probability(value):
    return round(clamp(value, 0.0, 0.995), 4)


def decode_count(value, ceiling):
    return clamp(math.expm1(value), 0.0, ceiling)


def predict_models(raw_features, regression, count_ceiling):
    basis = build_basis(raw_features, regression["stats"])
    probability_score = sum(weight * feature for weight, feature in zip(regression["models"]["probability"]["weights"], basis))
    min_score = sum(weight * feature for weight, feature in zip(regression["models"]["catchMin"]["weights"], basis))
    max_score = sum(weight * feature for weight, feature in zip(regression["models"]["catchMax"]["weights"], basis))

    predicted_min = decode_count(min_score, count_ceiling)
    predicted_max = max(predicted_min, decode_count(max_score, count_ceiling))

    return {
        "probability": clip_probability(probability_score),
        "predictedMin": round(predicted_min, 2),
        "predictedMax": round(predicted_max, 2),
    }


def main():
    args = parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()
    target_year = args.year if args.year else today.year
    year_start = date(target_year, 1, 1)
    year_end = date(target_year, 12, 31)

    training_start = date(target_year - 2, 1, 1)
    results = collect_daily_results(oldest_keep_date=training_start)
    results = [row for row in results if row["date"] <= today]
    if not results:
        raise RuntimeError("No torafugu results were collected.")

    archive_start = date(results[0]["date"].year, 1, 1)
    archive_end = min(today, year_end)

    air_archive = fetch_open_meteo_daily(
        "https://archive-api.open-meteo.com/v1/archive",
        archive_start,
        archive_end,
        ["temperature_2m_mean"],
    )
    sea_archive = fetch_open_meteo_daily(
        "https://marine-api.open-meteo.com/v1/marine",
        archive_start,
        archive_end,
        ["sea_surface_temperature_mean"],
    )
    archive_features = combine_feature_sources(air_archive, sea_archive)

    forecast_features = {}
    if today < year_end:
        forecast_end = min(today + timedelta(days=15), year_end)
        air_forecast = fetch_open_meteo_daily(
            "https://api.open-meteo.com/v1/forecast",
            today,
            forecast_end,
            ["temperature_2m_mean"],
        )
        sea_forecast = fetch_open_meteo_daily(
            "https://marine-api.open-meteo.com/v1/marine",
            today,
            forecast_end,
            ["sea_surface_temperature_mean"],
        )
        forecast_features = combine_feature_sources(air_forecast, sea_forecast)

    climatology = build_climatology(archive_features)
    positive_threshold = max(4, math.ceil(quantile([row["catchMax"] for row in results], 0.85)))

    training_rows = []
    for row in results:
        feature_record, _ = resolve_feature(row["date"], archive_features, forecast_features, climatology)
        training_rows.append(
            {
                "date": row["date"],
                "catchMin": row["catchMin"],
                "catchMax": row["catchMax"],
                "fishNum": row["fishNum"],
                "url": row["url"],
                "airTemp": feature_record["temperature_2m_mean"],
                "seaTemp": feature_record["sea_surface_temperature_mean"],
                "moonAge": moon_age_for(row["date"]),
            }
        )

    stats = compute_base_stats(training_rows)
    design_matrix = [build_basis(row, stats) for row in training_rows]

    probability_targets = [1.0 if row["catchMax"] >= positive_threshold else 0.0 for row in training_rows]
    min_targets = [math.log1p(row["catchMin"]) for row in training_rows]
    max_targets = [math.log1p(row["catchMax"]) for row in training_rows]

    count_ceiling = max(row["catchMax"] for row in training_rows) * 1.35 + 1.0
    regression = {
        "featureTerms": FEATURE_TERMS,
        "stats": {
            "means": {key: round(stats["means"][key], 6) for key in FEATURE_KEYS},
            "scales": {key: round(stats["scales"][key], 6) for key in FEATURE_KEYS},
        },
        "countCeiling": round(count_ceiling, 3),
        "models": {
            "probability": {
                "type": "clamped_linear",
                "weights": [round(value, 8) for value in fit_ridge_regression(design_matrix, probability_targets, ridge=1.1)],
            },
            "catchMin": {
                "type": "log_count",
                "weights": [round(value, 8) for value in fit_ridge_regression(design_matrix, min_targets, ridge=0.75)],
            },
            "catchMax": {
                "type": "log_count",
                "weights": [round(value, 8) for value in fit_ridge_regression(design_matrix, max_targets, ridge=0.75)],
            },
        },
    }

    observed_map = {row["date"].isoformat(): row for row in training_rows if row["date"].year == target_year}
    predictions = []
    prediction_features = []

    current = year_start
    while current <= year_end:
        feature_record, source = resolve_feature(current, archive_features, forecast_features, climatology)
        raw_features = {
            "airTemp": feature_record["temperature_2m_mean"],
            "seaTemp": feature_record["sea_surface_temperature_mean"],
            "moonAge": moon_age_for(current),
        }
        model_output = predict_models(raw_features, regression, count_ceiling)
        observed = observed_map.get(current.isoformat())
        predictions.append(
            {
                "date": current.isoformat(),
                "probability": model_output["probability"],
                "predictedMin": model_output["predictedMin"],
                "predictedMax": model_output["predictedMax"],
                "airTemp": round(raw_features["airTemp"], 2),
                "seaTemp": round(raw_features["seaTemp"], 2),
                "moonAge": round(raw_features["moonAge"], 2),
                "featureSource": source,
                "observedMin": round(observed["catchMin"], 2) if observed else None,
                "observedMax": round(observed["catchMax"], 2) if observed else None,
                "fishNum": observed["fishNum"] if observed else None,
                "url": observed["url"] if observed else None,
            }
        )
        prediction_features.append(raw_features)
        current += timedelta(days=1)

    top_days = sorted(
        [row for row in predictions if row["date"] >= today.isoformat()],
        key=lambda item: item["probability"],
        reverse=True,
    )[:8]

    air_values = [row["airTemp"] for row in prediction_features]
    sea_values = [row["seaTemp"] for row in prediction_features]
    today_prediction = next((row for row in predictions if row["date"] == today.isoformat()), predictions[0])

    payload = {
        "targetYear": target_year,
        "today": today.isoformat(),
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "xDayThreshold": positive_threshold,
        "sourceRange": {
            "from": results[0]["date"].isoformat(),
            "to": results[-1]["date"].isoformat(),
            "count": len(results),
        },
        "featureRanges": {
            "airTemp": {
                "min": round_feature_range(air_values, lower_pad=1.0)[0],
                "max": round_feature_range(air_values, upper_pad=1.0)[1],
                "step": 0.1,
                "default": today_prediction["airTemp"],
            },
            "seaTemp": {
                "min": round_feature_range(sea_values, lower_pad=0.5)[0],
                "max": round_feature_range(sea_values, upper_pad=0.5)[1],
                "step": 0.1,
                "default": today_prediction["seaTemp"],
            },
            "moonAge": {
                "min": 0.0,
                "max": round(SYNODIC_MONTH, 2),
                "step": 0.1,
                "default": today_prediction["moonAge"],
            },
        },
        "regression": regression,
        "observed": [
            {
                "date": row["date"].isoformat(),
                "catchMin": row["catchMin"],
                "catchMax": row["catchMax"],
                "fishNum": row["fishNum"],
                "url": row["url"],
                "airTemp": round(row["airTemp"], 2),
                "seaTemp": round(row["seaTemp"], 2),
                "moonAge": round(row["moonAge"], 2),
            }
            for row in training_rows
            if row["date"].year == target_year
        ],
        "topDays": top_days,
        "predictions": predictions,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
