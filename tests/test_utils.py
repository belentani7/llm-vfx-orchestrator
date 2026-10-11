"""Tests for orchestrator.utils."""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.utils import (
    JSONExtractionError,
    atomic_write_json,
    atomic_write_text,
    backoff_delay,
    coerce_score,
    extract_json,
    gather_bounded,
    read_json,
    retry_after_seconds,
    truncate,
)


class TestExtractJson:
    def test_plain_object(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_markdown_fence(self):
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_fence_without_language(self):
        assert extract_json('```\n[1, 2, 3]\n```') == [1, 2, 3]

    def test_prose_around_payload(self):
        raw = 'Sure! Here is the workflow:\n{"3": {"class_type": "KSampler"}}\nHope it helps.'
        assert extract_json(raw) == {"3": {"class_type": "KSampler"}}

    def test_nested_braces_in_strings(self):
        raw = 'text {"a": "} not the end {", "b": {"c": [1, 2]}} tail'
        assert extract_json(raw) == {"a": "} not the end {", "b": {"c": [1, 2]}}

    def test_trailing_comma_repair(self):
        assert extract_json('{"a": 1, "b": [1, 2,],}') == {"a": 1, "b": [1, 2]}

    def test_garbage_raises(self):
        with pytest.raises(JSONExtractionError):
            extract_json("no json here at all")

    def test_non_string_raises(self):
        with pytest.raises(JSONExtractionError):
            extract_json(None)  # type: ignore[arg-type]


class TestCoerceScore:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (0.85, 0.85),
            (1, 1.0),
            ("0.72", 0.72),
            ("85%", 0.85),
            ("8.5/10", 0.85),
            ("Score: 9/10", 0.9),
            (9, 0.9),
            ("excellent", 0.0),
            (None, 0.0),
            (True, 0.0),
            (-3, 0.0),
            (1.4, 0.14),
        ],
    )
    def test_values(self, raw, expected):
        assert coerce_score(raw) == pytest.approx(expected)

    def test_default_used_for_missing(self):
        assert coerce_score(None, default=0.5) == 0.5


class TestBackoff:
    def test_grows_and_caps(self):
        assert backoff_delay(0, jitter=0) == pytest.approx(0.5)
        assert backoff_delay(3, jitter=0) == pytest.approx(4.0)
        assert backoff_delay(20, jitter=0) == pytest.approx(30.0)

    def test_jitter_stays_positive(self):
        for attempt in range(10):
            assert backoff_delay(attempt, base=0.1, jitter=0.25) >= 0

    def test_retry_after_parse(self):
        assert retry_after_seconds("2.5") == pytest.approx(2.5)
        assert retry_after_seconds(None) is None
        assert retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") is None
        assert retry_after_seconds("-4") == 0.0


class TestAtomicIo:
    def test_roundtrip(self, tmp_path):
        path = tmp_path / "nested" / "data.json"
        atomic_write_json(path, {"a": [1, 2]})
        assert read_json(path) == {"a": [1, 2]}

    def test_no_temp_files_left(self, tmp_path):
        atomic_write_text(tmp_path / "x.txt", "hello")
        assert [p.name for p in tmp_path.iterdir()] == ["x.txt"]

    def test_read_json_default_on_corrupt(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        assert read_json(path, default={"fallback": True}) == {"fallback": True}

    def test_read_json_missing(self, tmp_path):
        assert read_json(tmp_path / "nope.json") is None


def test_truncate():
    assert truncate("abcdef", 4).endswith("…")
    assert len(truncate("abcdef", 4)) == 4
    assert truncate("abc", 10) == "abc"


class TestGatherBounded:
    @pytest.mark.asyncio
    async def test_preserves_order_and_limits_concurrency(self):
        inflight = 0
        peak = 0

        async def work(value: int) -> int:
            nonlocal inflight, peak
            inflight += 1
            peak = max(peak, inflight)
            try:
                await asyncio.sleep(0.01)
                return value * 2
            finally:
                inflight -= 1

        results = await gather_bounded([work(i) for i in range(8)], 3)
        assert results == [i * 2 for i in range(8)]
        assert peak == 3

    @pytest.mark.asyncio
    async def test_empty(self):
        assert await gather_bounded([], 4) == []
