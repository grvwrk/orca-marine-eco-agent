"""Build deterministic ORCA demo fixtures without network access."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


REGIONS = [
    ("Gujarat Gulf of Kutch", 22.7, 69.0, "favourable"),
    ("Maharashtra Konkan", 16.8, 73.0, "conflict"),
    ("Goa Offshore", 15.1, 73.75, "protected"),
    ("Karnataka Coast", 14.2, 74.5, "favourable"),
    ("Kerala Coast", 10.2, 76.1, "calm_poor"),
    ("Chennai Coast", 13.08, 80.27, "storm"),
    ("Andhra Coast", 16.7, 82.2, "moderate"),
    ("Odisha Coast", 19.8, 85.8, "storm"),
    ("Northern Bay of Bengal", 21.0, 88.0, "sparse"),
    ("Arabian Sea Offshore", 15.0, 68.0, "moderate"),
    ("Bay of Bengal Offshore", 15.0, 90.0, "sparse"),
]


def polygon(lat: float, lon: float, size: float = 0.35) -> dict:
    return {"type": "Polygon", "coordinates": [[[lon - size, lat - size], [lon + size, lat - size], [lon + size, lat + size], [lon - size, lat + size], [lon - size, lat - size]]]}


def feature(geometry: dict, properties: dict) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def build(target: date, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    pfz: list[dict] = []
    weather: list[dict] = []
    ocean: list[dict] = []
    satellite: list[dict] = []
    boundaries: list[dict] = []
    ordered_regions = sorted(REGIONS, key=lambda item: 0 if item[0] == "Goa Offshore" else 1)
    for index, (name, lat, lon, scenario) in enumerate(ordered_regions):
        if scenario != "sparse":
            potential = "high" if scenario in {"favourable", "conflict", "protected", "storm"} else "moderate" if scenario == "moderate" else "low"
            pfz.append(feature(polygon(lat, lon), {"region_name": f"{name} PFZ", "issued_date": target.isoformat(), "valid_until": (target + timedelta(days=2)).isoformat(), "chlorophyll_level": "high" if potential == "high" else "low", "sst_range": "28-30C" if potential == "high" else "25-27C", "advisory_text": f"{potential.title()} potential in the {name} sector.", "source": "ORCA Demo Fixture (provider reference: INCOIS)", "source_url": "demo://orca/pfz"}))
        if scenario in {"conflict", "storm"}:
            weather.append(feature(polygon(lat, lon, 0.8), {"alert_type": "cyclone_watch" if scenario == "storm" else "fishermen_warning", "severity": "severe" if scenario == "storm" else "high", "valid_from": (target - timedelta(hours=1)).isoformat() + "T00:00:00Z", "valid_until": (target + timedelta(days=1)).isoformat() + "T00:00:00Z", "description": "Operational risk is elevated despite fishing potential.", "source": "ORCA Demo Fixture (provider reference: IMD)", "source_url": "demo://orca/weather"}))
        elif scenario != "sparse":
            weather.append(feature(polygon(lat, lon, 0.5), {"alert_type": "weather_observation", "severity": "low", "valid_from": target.isoformat() + "T00:00:00Z", "valid_until": (target + timedelta(days=1)).isoformat() + "T00:00:00Z", "description": "No severe alert in the demo sector.", "source": "ORCA Demo Fixture (provider reference: IMD)", "source_url": "demo://orca/weather"}))
        if scenario != "sparse":
            for hour, wave, wind in ((6, 0.8, 14.0), (12, 1.2 if scenario in {"conflict", "storm"} else 0.9, 22.0 if scenario in {"conflict", "storm"} else 16.0), (18, 1.8 if scenario == "storm" else 1.2, 30.0 if scenario == "storm" else 18.0)):
                ocean.append(feature({"type": "Point", "coordinates": [lon, lat]}, {"forecast_time": (datetime.combine(target, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=hour)).isoformat().replace("+00:00", "Z"), "wave_height_m": wave, "wind_speed_kmh": wind, "current_speed_ms": 0.6 if scenario == "calm_poor" else 1.1, "tide_level_m": 1.0 + hour / 24, "source": "ORCA Demo Fixture (provider reference: INCOIS OSF)", "source_url": "demo://orca/ocean"}))
            for product, value in (("chlorophyll", 1.8 if scenario in {"favourable", "conflict", "protected"} else 0.25 if scenario == "calm_poor" else 0.9), ("sst", 29.0 if scenario != "calm_poor" else 26.0)):
                satellite.append(feature({"type": "Point", "coordinates": [lon, lat]}, {"product": product, "value": value, "unit": "mg/m3" if product == "chlorophyll" else "C", "observed_at": target.isoformat() + "T00:00:00Z", "source": "ORCA Demo Fixture (provider reference: Oceansat)", "source_url": "demo://orca/satellite"}))
            boundary_type = "MPA" if scenario == "protected" else "EEZ"
            boundary_name = "Goa coastal protected zone" if name == "Goa Offshore" and boundary_type == "MPA" else f"{name} {'protected zone' if boundary_type == 'MPA' else 'EEZ corridor'}"
            boundaries.append(feature(polygon(lat, lon, 0.18 if scenario == "protected" else 1.0), {"boundary_type": boundary_type, "name": boundary_name, "metadata": {"data_status": "DEMO_FIXTURE", "scenario": scenario}, "source_url": "demo://orca/boundaries"}))
    for filename, records in (("pfz_demo.json", pfz), ("weather_demo.json", weather), ("ocean_demo.json", ocean), ("satellite_demo.json", satellite), ("boundary_demo.json", boundaries)):
        (output / filename).write_text(json.dumps({"type": "FeatureCollection", "features": records}, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(pfz)} PFZ, {len(weather)} weather, {len(ocean)} ocean, {len(satellite)} satellite, and {len(boundaries)} boundary fixtures in {output}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/demo/scenarios"))
    parser.add_argument("--target-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    build(args.target_date, args.output_dir)


if __name__ == "__main__":
    main()