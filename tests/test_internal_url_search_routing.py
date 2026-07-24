"""Regression tests for internal URL retrieval routing."""

from pathlib import Path
import subprocess

from Conversation import (
    _all_links_are_internal,
    _internal_reader_tool_names,
    _is_internal_url,
    _normalize_perplexity_result,
)
from agents.search_and_information_agents import _normalize_search_agent_chunk_text


G3DOC_URL = (
    "https://g3doc.corp.google.com/search/g3doc/search-edu/"
    "search_light/index.md?cl=head"
)


def test_all_links_are_internal_accepts_g3doc_urls():
    assert _all_links_are_internal([G3DOC_URL])


def test_is_internal_url_recognizes_g3doc():
    assert _is_internal_url(G3DOC_URL)


def test_is_internal_url_recognizes_any_corp_google_subdomain():
    assert _is_internal_url("https://new-service.corp.google.com/page")


def test_all_links_are_internal_rejects_mixed_public_urls():
    assert not _all_links_are_internal([G3DOC_URL, "https://example.com/article"])


def test_ui_parser_does_not_treat_url_path_as_search_command():
    parser_path = Path("interface/parseMessageForCheckBoxes.js")
    script = """
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const context = { console: { log() {} }, window: {} };
vm.createContext(context);
vm.runInContext(source, context);
const result = context.parseMessageForCheckBoxes(process.argv[2]);
if (result.perform_web_search !== undefined) {
  throw new Error(JSON.stringify(result));
}
"""
    subprocess.run(
        ["node", "-e", script, str(parser_path), G3DOC_URL],
        check=True,
        text=True,
        capture_output=True,
    )


def test_internal_reader_tool_names_prefers_ckt_read_url():
    assert _internal_reader_tool_names({"read_url", "read_internal_page"}) == ["read_url"]


def test_reply_suppresses_public_search_when_every_link_is_internal():
    source = Path("Conversation.py").read_text()

    assert "if _all_links_are_internal(links) and (perform_web_search or google_scholar):" in source
    assert "[INTERNAL-URL] Suppressing public search for internal URLs" in source
    assert "[INTERNAL-URL] Skipping generic link reader for internal URLs" in source
    assert "perform_web_search = False" in source
    assert "google_scholar = False" in source


def test_enabled_tools_force_internal_reader_for_internal_url():
    source = Path("Conversation.py").read_text()

    assert "[_get_enabled_tools] Internal URLs detected" in source
    assert "reader_names = _internal_reader_tool_names(available_names)" in source


def test_normalize_search_agent_chunk_text_consumes_iterable_text():
    assert _normalize_search_agent_chunk_text({"text": iter(["one", " two"])}) == "one two"


def test_normalize_search_agent_chunk_text_returns_string_text_unchanged():
    assert _normalize_search_agent_chunk_text({"text": "answer"}) == "answer"


def test_normalize_perplexity_result_extracts_error_text_from_mapping():
    assert _normalize_perplexity_result({"text": "search failed"}) == "search failed"
