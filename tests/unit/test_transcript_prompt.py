"""The transcript prompt prefix must be byte-identical across calls.

Prompt caching is what makes repeated questions about one video affordable: five
questions cost 1.25 + 4 x 0.1 = 1.65x a single call instead of 5x -- but only while
everything ahead of the cache point stays byte-for-byte the same.
"""

from pydantic_ai import CachePoint

from webtonotion.agents.prompts import (
    build_segment_index,
    build_transcript_prompt,
    format_timestamp,
)
from webtonotion.models.transcript import TranscriptSegment

BODY = "a spoken sentence about gardening"


def test_prefix_is_identical_across_different_questions():
    first = build_transcript_prompt(BODY, "what is this about?")
    second = build_transcript_prompt(BODY, "who is speaking?")

    assert first[0] == second[0]


def test_prefix_is_identical_across_repeated_calls():
    calls = [build_transcript_prompt(BODY, "q")[0] for _ in range(3)]

    assert len(set(calls)) == 1


def test_cache_point_sits_between_the_body_and_the_question():
    parts = build_transcript_prompt(BODY, "what is this about?")

    assert len(parts) == 3
    assert BODY in parts[0]
    assert isinstance(parts[1], CachePoint)
    assert parts[2] == "what is this about?"


def test_cache_point_ttl_is_configurable():
    parts = build_transcript_prompt(BODY, "q", cache_ttl="5m")

    assert parts[1].ttl == "5m"


def test_a_different_body_produces_a_different_prefix():
    first = build_transcript_prompt("body one", "q")
    second = build_transcript_prompt("body two", "q")

    assert first[0] != second[0]


def test_format_timestamp_switches_to_hours_past_an_hour():
    assert format_timestamp(0) == "00:00"
    assert format_timestamp(75) == "01:15"
    assert format_timestamp(3675) == "1:01:15"


def test_segment_index_is_timestamped_and_capped():
    segments = [
        TranscriptSegment(start=float(i * 10), end=float(i * 10 + 10), text=f"line {i}")
        for i in range(100)
    ]

    index = build_segment_index(segments, max_lines=5)

    lines = index.splitlines()
    assert len(lines) == 5
    assert lines[0].startswith("[00:00]")


def test_segment_index_of_no_segments_is_empty():
    assert build_segment_index([]) == ""
