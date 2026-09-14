import json
from collections.abc import Iterable
from typing import Any

import requests

from orca.config import settings
from orca.knowledge.database import PostGISDatabase


def fetch_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any] | list[Any]:
    request_headers = {"Accept": "application/json, application/geo+json", **(headers or {})}
    response = requests.get(
        url,
        timeout=settings.request_timeout_seconds,
        headers=request_headers,
        verify=settings.ca_bundle,
    )
    response.raise_for_status()
    return response.json()


def features(payload: dict[str, Any] | list[Any]) -> Iterable[dict[str, Any]]:
    if isinstance(payload, list):
        yield from payload
    elif payload.get("type") == "FeatureCollection":
        yield from payload.get("features", [])
    elif payload.get("type") == "Feature":
        yield payload
    else:
        yield payload


def properties(feature: dict[str, Any]) -> dict[str, Any]:
    return feature.get("properties", feature)


def geometry_json(feature: dict[str, Any]) -> str:
    return json.dumps(feature.get("geometry", feature))


def load(database_url: str, query: str, params: dict[str, Any]) -> None:
    PostGISDatabase(database_url).execute(query, params)
