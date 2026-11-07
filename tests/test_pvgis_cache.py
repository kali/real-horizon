"""PVGIS disk cache: read hit, and a corrupt file falls through to a refetch."""

from __future__ import annotations

import json

import pytest

from custom_components.real_horizon.pvgis import fetch_pvgis


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    async def json(self):
        return self._payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return _Resp(self.payload)


async def test_cache_hit_skips_network(tmp_path) -> None:
    cache = tmp_path / "pvgis.json"
    cache.write_text(json.dumps({"cached": True}))
    session = _Session({"cached": False})
    assert await fetch_pvgis(session, 1.0, 2.0, cache) == {"cached": True}
    assert session.calls == 0


@pytest.mark.parametrize("content", [None, "not json"])
async def test_missing_or_corrupt_cache_refetches(tmp_path, content) -> None:
    cache = tmp_path / "sub" / "pvgis.json"
    if content is not None:
        cache.parent.mkdir()
        cache.write_text(content)
    session = _Session({"fresh": 1})
    assert await fetch_pvgis(session, 1.0, 2.0, cache) == {"fresh": 1}
    assert session.calls == 1
    assert json.loads(cache.read_text()) == {"fresh": 1}
