import pytest
from app.search import parse_search_results

def test_parse_search_results_empty():
    assert parse_search_results([]) == []

def test_parse_search_results_deduplicates():
    rows = [
        {"id": "1", "slug": "a", "title": "A", "summary": "", "score": 0.9},
        {"id": "1", "slug": "a", "title": "A", "summary": "", "score": 0.8},
        {"id": "2", "slug": "b", "title": "B", "summary": "", "score": 0.7},
    ]
    results = parse_search_results(rows)
    assert len(results) == 2
    assert results[0]["slug"] == "a"
