import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.search import parse_search_results, search_pages


# ---------------------------------------------------------------------------
# parse_search_results — pure function
# ---------------------------------------------------------------------------


def test_parse_search_results_empty():
    assert parse_search_results([]) == []


def test_parse_search_results_single_row():
    rows = [{"id": "p1", "slug": "notes/one", "title": "One", "summary": "s", "score": 0.8}]
    result = parse_search_results(rows)
    assert result == rows


def test_parse_search_results_deduplicates_keeps_highest_score():
    rows = [
        {"id": "p1", "slug": "notes/one", "title": "One", "summary": "s", "score": 0.5},
        {"id": "p1", "slug": "notes/one", "title": "One", "summary": "s", "score": 0.9},
    ]
    result = parse_search_results(rows)
    assert len(result) == 1
    assert result[0]["score"] == 0.9


def test_parse_search_results_sorted_descending():
    rows = [
        {"id": "p1", "slug": "a", "title": "A", "summary": "", "score": 0.3},
        {"id": "p2", "slug": "b", "title": "B", "summary": "", "score": 0.9},
        {"id": "p3", "slug": "c", "title": "C", "summary": "", "score": 0.6},
    ]
    result = parse_search_results(rows)
    scores = [r["score"] for r in result]
    assert scores == sorted(scores, reverse=True)


def test_parse_search_results_multiple_duplicates():
    rows = [
        {"id": "p1", "slug": "a", "title": "A", "summary": "", "score": 0.2},
        {"id": "p2", "slug": "b", "title": "B", "summary": "", "score": 0.7},
        {"id": "p1", "slug": "a", "title": "A", "summary": "", "score": 0.4},
        {"id": "p2", "slug": "b", "title": "B", "summary": "", "score": 0.5},
    ]
    result = parse_search_results(rows)
    assert len(result) == 2
    by_id = {r["id"]: r["score"] for r in result}
    assert by_id["p1"] == 0.4
    assert by_id["p2"] == 0.7


# ---------------------------------------------------------------------------
# search_pages — async, VECTOR_SEARCH_ENABLED=false (set in conftest)
# So _workspace_has_page_embeddings is irrelevant; the text-search path runs.
# ---------------------------------------------------------------------------


@pytest.fixture
def session():
    s = AsyncMock(spec=AsyncSession)
    s.add = MagicMock()
    s.delete = AsyncMock()
    return s


def _fake_row(id_, slug, title, summary, score):
    """Build a row mock whose ._mapping behaves like a dict."""
    row = MagicMock()
    row._mapping = {"id": id_, "slug": slug, "title": title, "summary": summary, "score": score}
    return row


@pytest.mark.asyncio
async def test_search_pages_text_path_returns_results(session):
    fake_rows = [
        _fake_row("p1", "notes/one", "One", "summary one", 0.8),
        _fake_row("p2", "notes/two", "Two", "summary two", 0.5),
    ]
    result_mock = MagicMock()
    result_mock.__iter__ = MagicMock(return_value=iter(fake_rows))
    session.execute.return_value = result_mock

    results = await search_pages(session, workspace_id="ws-1", query="one two")

    assert len(results) == 2
    assert results[0]["slug"] == "notes/one"
    assert results[1]["slug"] == "notes/two"


@pytest.mark.asyncio
async def test_search_pages_passes_workspace_id_and_limit(session):
    result_mock = MagicMock()
    result_mock.__iter__ = MagicMock(return_value=iter([]))
    session.execute.return_value = result_mock

    await search_pages(session, workspace_id="ws-abc", query="test", limit=3)

    session.execute.assert_called_once()
    _, call_kwargs = session.execute.call_args
    # params dict is the second positional argument
    call_args = session.execute.call_args[0]
    params = call_args[1] if len(call_args) > 1 else session.execute.call_args[1].get("params", {})
    assert params["ws_id"] == "ws-abc"
    assert params["query"] == "test"
    assert params["limit"] == 3


@pytest.mark.asyncio
async def test_search_pages_empty_results(session):
    result_mock = MagicMock()
    result_mock.__iter__ = MagicMock(return_value=iter([]))
    session.execute.return_value = result_mock

    results = await search_pages(session, workspace_id="ws-1", query="nothing")

    assert results == []


@pytest.mark.asyncio
async def test_search_pages_default_limit_is_five(session):
    result_mock = MagicMock()
    result_mock.__iter__ = MagicMock(return_value=iter([]))
    session.execute.return_value = result_mock

    await search_pages(session, workspace_id="ws-1", query="anything")

    call_args = session.execute.call_args[0]
    params = call_args[1]
    assert params["limit"] == 5


@pytest.mark.asyncio
async def test_search_pages_returns_list_of_dicts(session):
    fake_rows = [_fake_row("p1", "a/b", "Title", "Sum", 0.9)]
    result_mock = MagicMock()
    result_mock.__iter__ = MagicMock(return_value=iter(fake_rows))
    session.execute.return_value = result_mock

    results = await search_pages(session, workspace_id="ws-1", query="title")

    assert isinstance(results, list)
    assert isinstance(results[0], dict)
    assert set(results[0].keys()) == {"id", "slug", "title", "summary", "score"}


@pytest.mark.asyncio
async def test_search_pages_single_execute_call_when_vector_disabled(session):
    """With VECTOR_SEARCH_ENABLED=false the embedding check is skipped entirely,
    so session.execute is called exactly once (the text-search SQL)."""
    result_mock = MagicMock()
    result_mock.__iter__ = MagicMock(return_value=iter([]))
    session.execute.return_value = result_mock

    await search_pages(session, workspace_id="ws-1", query="hello")

    assert session.execute.call_count == 1
