#!/usr/bin/env python3
import argparse
import html
import json
import math
import re
import urllib.parse
import urllib.request
from collections import defaultdict
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


def collect_daily_results():
    daily = {}
    seen_urls = set()
    for page in range(1, 121):
        html_text = fetch_text(MANEIMARU_HOME) if page == 1 else fetch_text(MANEIMARU_PAGE_API, {"p": page})
        if html_text.strip().startswith("nodata"):
            break
        page_posts = parse_posts(html_text)

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
    ordered = [daily[key] for key in sorted(daily.keys())]
    return ordered


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


def circular_distance(day_a, day_b, span=366):
    delta = abs(day_a - day_b)
    return min(delta, span - delta)


def build_climatology(feature_map):
    buckets = defaultdict(lambda: {"temperature_2m_mean": [], "sea_surface_temperature_mean": []})
    for iso, values in feature_map.items():
        if "temperature_2m_mean" not in values or "sea_surface_temperature_mean" not in values:
            continue
        if values["temperature_2m_mean"] is None or values["sea_surface_temperature_mean"] is None:
            continue
        day = date.fromisoformat(iso)
        doy = day.timetuple().tm_yday
        buckets[doy]["temperature_2m_mean"].append(values["temperature_2m_mean"])
        buckets[doy]["sea_surface_temperature_mean"].append(values["sea_surface_temperature_mean"])

    global_air = []
    global_sea = []
    for values in buckets.values():
        global_air.extend(values["temperature_2m_mean"])
        global_sea.extend(values["sea_surface_temperature_mean"])

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


def build_activity_curve(training_days):
    counts = defaultdict(int)
    for day in training_days:
        counts[day.timetuple().tm_yday] += 1

    curve = {}
    peak = 0.0
    for doy in range(1, 367):
        score = 0.0
        for active_doy, count in counts.items():
            distance = circular_distance(doy, active_doy)
            score += count * math.exp(-0.5 * (distance / 16.0) ** 2)
        curve[doy] = score
        peak = max(peak, score)

    for doy in curve:
        curve[doy] = curve[doy] / peak if peak else 0.0
    return curve


def standardize(samples):
    dimensions = len(samples[0])
    means = []
    scales = []
    for dim in range(dimensions):
        values = [sample[dim] for sample in samples]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        means.append(mean)
        scales.append(math.sqrt(variance) or 1.0)
    return means, scales


def normalize(features, means, scales):
    return [(value - mean) / scale for value, mean, scale in zip(features, means, scales)]


def kernel_probability(target, training_rows, prior, bandwidth, skip_index=None):
    weighted_sum = 0.0
    total_weight = 0.0
    for index, row in enumerate(training_rows):
        if index == skip_index:
            continue
        distance_sq = sum((target[dim] - row["vector"][dim]) ** 2 for dim in range(len(target)))
        weight = math.exp(-0.5 * distance_sq / (bandwidth * bandwidth))
        year_gap = training_rows[-1]["date"].year - row["date"].year
        weight *= 1.0 / (1.0 + year_gap * 0.28)
        weighted_sum += weight * row["label"]
        total_weight += weight
    smooth = 0.75
    return (weighted_sum + prior * smooth) / (total_weight + smooth)


def choose_bandwidth(training_rows, prior):
    candidates = [0.55, 0.7, 0.9, 1.1, 1.35, 1.6]
    best_bandwidth = candidates[0]
    best_score = float("inf")
    for candidate in candidates:
        error = 0.0
        for index, row in enumerate(training_rows):
            prediction = kernel_probability(row["vector"], training_rows, prior, candidate, skip_index=index)
            error += (prediction - row["label"]) ** 2
        score = error / len(training_rows)
        if score < best_score:
            best_score = score
            best_bandwidth = candidate
    return best_bandwidth


def build_feature_vector(feature_record, day):
    moon_age = moon_age_for(day)
    moon_phase = moon_age / SYNODIC_MONTH * math.tau
    return [
        feature_record["temperature_2m_mean"],
        feature_record["sea_surface_temperature_mean"],
        math.sin(moon_phase),
        math.cos(moon_phase),
    ]


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
    return baseline, "climatology"


def main():
    args = parse_args()
    today = date.fromisoformat(args.today) if args.today else date.today()
    target_year = args.year if args.year else today.year
    year_start = date(target_year, 1, 1)
    year_end = date(target_year, 12, 31)

    results = collect_daily_results()
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
    training_days = [row["date"] for row in results]
    activity_curve = build_activity_curve(training_days)

    raw_vectors = []
    training_rows = []
    for row in results:
        feature_record, _ = resolve_feature(row["date"], archive_features, forecast_features, climatology)
        vector = build_feature_vector(feature_record, row["date"])
        raw_vectors.append(vector)
        training_rows.append(
            {
                "date": row["date"],
                "label": 1.0 if row["catchMax"] >= positive_threshold else 0.0,
                "catchMax": row["catchMax"],
                "fishNum": row["fishNum"],
                "url": row["url"],
                "featureRecord": feature_record,
            }
        )

    means, scales = standardize(raw_vectors)
    for row, vector in zip(training_rows, raw_vectors):
        row["vector"] = normalize(vector, means, scales)

    prior = sum(row["label"] for row in training_rows) / len(training_rows)
    bandwidth = choose_bandwidth(training_rows, prior)

    predictions = []
    current = year_start
    while current <= year_end:
        feature_record, source = resolve_feature(current, archive_features, forecast_features, climatology)
        normalized_vector = normalize(build_feature_vector(feature_record, current), means, scales)
        raw_probability = kernel_probability(normalized_vector, training_rows, prior, bandwidth)
        activity = activity_curve[current.timetuple().tm_yday]
        probability = max(0.0, min(0.995, raw_probability * activity))
        predictions.append(
            {
                "date": current.isoformat(),
                "probability": round(probability, 4),
                "airTemp": round(feature_record["temperature_2m_mean"], 2),
                "seaTemp": round(feature_record["sea_surface_temperature_mean"], 2),
                "moonAge": round(moon_age_for(current), 2),
                "featureSource": source,
            }
        )
        current += timedelta(days=1)

    observed_map = {row["date"].isoformat(): row for row in results if row["date"].year == target_year}
    top_days = sorted(
        [row for row in predictions if row["date"] >= today.isoformat()],
        key=lambda item: item["probability"],
        reverse=True,
    )[:8]

    payload = {
        "targetYear": target_year,
        "today": today.isoformat(),
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "xDayThreshold": positive_threshold,
        "bandwidth": bandwidth,
        "sourceRange": {
            "from": results[0]["date"].isoformat(),
            "to": results[-1]["date"].isoformat(),
            "count": len(results),
        },
        "observed": [
            {
                "date": iso,
                "catchMax": row["catchMax"],
                "fishNum": row["fishNum"],
                "url": row["url"],
            }
            for iso, row in sorted(observed_map.items())
        ],
        "topDays": top_days,
        "predictions": predictions,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
