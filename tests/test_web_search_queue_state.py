"""Regression tests for previous-turn web-search result reuse."""

from pathlib import Path

import requests

import base
from base import _normalize_previous_turn_search_results


def test_normalize_previous_turn_search_results_rejects_legacy_empty_string():
    assert _normalize_previous_turn_search_results("") is None


def test_normalize_previous_turn_search_results_retains_valid_result_mapping():
    previous_results = {
        "queries": ["example query"],
        "links": [{"title": "Example", "link": "https://example.test"}],
    }

    assert _normalize_previous_turn_search_results(previous_results) == previous_results


def test_normalize_previous_turn_search_results_rejects_incomplete_mapping():
    assert _normalize_previous_turn_search_results({"queries": ["example"]}) is None


def test_conversation_starts_new_web_search_without_legacy_empty_string_state():
    source = Path("Conversation.py").read_text()

    assert "previous_turn_search_results=None" in source
    assert "previous_turn_search_results=\"\"" not in source


def test_brightdata_google_serp_returns_empty_results_for_proxy_errors(monkeypatch):
    calls = []

    def raise_proxy_error(*args, **kwargs):
        calls.append((args, kwargs))
        raise requests.exceptions.ProxyError("407 Zone not found")

    monkeypatch.setattr(requests, "get", raise_proxy_error)

    assert base.brightdata_google_serp(
        "example query", "http://invalid-proxy", 10, only_pdf=None,
        only_science_sites=None,
    ) == []
    assert len(calls) == 1
