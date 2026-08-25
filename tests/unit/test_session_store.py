"""Unit tests for :class:`SqliteStore`.

Exercises the Pydantic AI message round-trip (tool calls/returns included),
append-only ordering, the concurrent-write conflict, and the confirm gate. No
live model is ever contacted.
"""

import pytest
from pydantic_ai import ModelMessagesTypeAdapter, models
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_core import to_jsonable_python

from webtonotion.agents.session import SessionConflictError, SqliteStore

models.ALLOW_MODEL_REQUESTS = False

pytestmark = pytest.mark.asyncio


@pytest.fixture
def store(tmp_path) -> SqliteStore:
    """Provide a schema-initialized store on a per-test temp database."""
    return SqliteStore(db_path=str(tmp_path / "cache" / "sessions.db"))


async def _fresh_store(tmp_path) -> SqliteStore:
    st = SqliteStore(db_path=str(tmp_path / "cache" / "sessions.db"))
    await st.init_schema()
    return st


def _history_with_tool_calls() -> list:
    """Hand-build a history that includes a tool call and its return."""
    return [
        ModelRequest(parts=[UserPromptPart(content="Save this to my reading list")]),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="find_databases",
                    args={"hint": "reading list"},
                    tool_call_id="call_1",
                )
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="find_databases",
                    content=[{"id": "db_1", "name": "Reading List"}],
                    tool_call_id="call_1",
                )
            ]
        ),
        ModelResponse(parts=[TextPart(content="I found your Reading List database.")]),
    ]


async def test_round_trip_preserves_tool_calls(tmp_path) -> None:
    """A history with tool call/return round-trips through the store intact."""
    st = await _fresh_store(tmp_path)
    session = await st.create("conv-1")

    original = _history_with_tool_calls()
    payloads = to_jsonable_python(original)
    await st.append_messages(session.id, 0, payloads)

    reloaded = await st.load_history(session.id, limit=100)

    assert reloaded == original
    # Sanity: the serialization is what a fresh adapter would produce too.
    assert reloaded == ModelMessagesTypeAdapter.validate_python(payloads)


async def test_append_only_ordering_across_turns(tmp_path) -> None:
    """Two successive appends load back in chronological order."""
    st = await _fresh_store(tmp_path)
    session = await st.create("conv-1")

    turn_one = [ModelRequest(parts=[UserPromptPart(content="first")])]
    turn_two = [ModelResponse(parts=[TextPart(content="second")])]

    seq0 = await st.next_seq(session.id)
    assert seq0 == 0
    await st.append_messages(session.id, seq0, to_jsonable_python(turn_one))

    seq1 = await st.next_seq(session.id)
    assert seq1 == 1
    await st.append_messages(session.id, seq1, to_jsonable_python(turn_two))

    reloaded = await st.load_history(session.id, limit=100)
    assert reloaded == turn_one + turn_two


async def test_concurrent_write_conflict(tmp_path) -> None:
    """Appending twice at the same seq_start raises SessionConflictError."""
    st = await _fresh_store(tmp_path)
    session = await st.create("conv-1")

    payloads = to_jsonable_python([ModelRequest(parts=[UserPromptPart(content="hi")])])
    await st.append_messages(session.id, 0, payloads)

    with pytest.raises(SessionConflictError):
        await st.append_messages(session.id, 0, payloads)


async def test_confirm_gate_set_then_clear(tmp_path) -> None:
    """set_confirmed_database sets a value, then clears it back to None."""
    st = await _fresh_store(tmp_path)
    session = await st.create("conv-1")

    assert session.confirmed_database_id is None

    await st.set_confirmed_database(session.id, "db_target")
    got = await st.get(session.id)
    assert got is not None
    assert got.confirmed_database_id == "db_target"

    await st.set_confirmed_database(session.id, None)
    got = await st.get(session.id)
    assert got is not None
    assert got.confirmed_database_id is None


async def test_next_seq_advances(tmp_path) -> None:
    """next_seq starts at 0 on an empty session and advances by row count."""
    st = await _fresh_store(tmp_path)
    session = await st.create("conv-1")

    assert await st.next_seq(session.id) == 0

    payloads = to_jsonable_python(
        [
            ModelRequest(parts=[UserPromptPart(content="a")]),
            ModelResponse(parts=[TextPart(content="b")]),
        ]
    )
    await st.append_messages(session.id, 0, payloads)

    assert await st.next_seq(session.id) == 2


async def test_get_missing_returns_none(tmp_path) -> None:
    """get on an unknown session id returns None."""
    st = await _fresh_store(tmp_path)
    assert await st.get("does-not-exist") is None


async def test_delete_removes_session_and_messages(tmp_path) -> None:
    """delete removes the session row and its message history."""
    st = await _fresh_store(tmp_path)
    session = await st.create("conv-1")
    await st.append_messages(
        session.id, 0, to_jsonable_python([ModelRequest(parts=[UserPromptPart(content="x")])])
    )

    await st.delete(session.id)

    assert await st.get(session.id) is None
    # Sequence numbering resets because the message rows are gone.
    assert await st.next_seq(session.id) == 0
