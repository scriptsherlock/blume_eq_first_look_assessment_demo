"""The keyless web-search Researcher agent."""
import pytest

from server import llm, search
from server.agents import researcher
from server.schema import Claim, EvidenceItem, ResearcherOut, SearchPlan

CLAIM = Claim(id="c1", kind="value", text="A UK utility cut site visits by 70%",
              quote="saves 70% of site surveys", source_url="https://www.blumeequity.com/insights/x")
PAGES = {
    "https://www.casestudies.com/wwu": "Wales & West Utilities reported that video surveys replaced 70% of site surveys in 2023. " * 5,
    "https://www.ofgem.gov.uk/report": "Network operators carried out 1.2 million site visits last year. " * 5,
}


@pytest.fixture
def agent(monkeypatch):
    seen = {}

    def fake_json(prompt, schema, model=None, system=None):
        seen.setdefault("prompts", []).append(prompt)
        if schema is SearchPlan:
            return SearchPlan(queries=["Wales West Utilities video survey site visits", "UK utility site visits"])
        return ResearcherOut(items=[
            EvidenceItem(stance="supports", summary="Customer reports 70%.", source_index=0,
                         quote="Wales & West Utilities reported that video surveys replaced 70% of site surveys in 2023."),
            EvidenceItem(stance="context", summary="Sector volume.", source_index=1,
                         quote="Network operators carried out 1.2 million site visits last year."),
        ])

    monkeypatch.setenv("SEARCH_PROVIDER", "web")
    monkeypatch.setattr(llm, "SEARCH_ENABLED", True)
    monkeypatch.setattr(llm, "generate_json", fake_json)
    monkeypatch.setattr(search, "web_search", lambda q, k=5: [
        search.Hit("https://www.blumeequity.com/insights/x", "The source post itself", ""),
        search.Hit("https://vyntelligence.com/blog/case", "Company blog", ""),
        search.Hit("https://www.casestudies.com/wwu", "WWU case study", ""),
        search.Hit("https://www.ofgem.gov.uk/report", "Ofgem report", ""),
        search.Hit("https://www.casestudies.com/wwu", "duplicate", ""),
    ])
    monkeypatch.setattr(search, "read_page", lambda url: PAGES.get(url))
    return seen


def test_finds_independent_evidence_with_checked_quotes(agent):
    ev = researcher.run("Vyntelligence", CLAIM)
    assert [e.url for e in ev] == ["https://www.casestudies.com/wwu", "https://www.ofgem.gov.uk/report"]
    assert [e.stance for e in ev] == ["supports", "context"]
    assert all(e.quote and e.quote in PAGES[e.url] for e in ev)
    judge_prompt = agent["prompts"][-1]
    assert "blumeequity.com" not in judge_prompt and "vyntelligence.com" not in judge_prompt  # not independent


def test_all_searches_failing_means_search_unavailable(agent, monkeypatch):
    def boom(q, k=5):
        raise RuntimeError("202 Ratelimit")
    monkeypatch.setattr(search, "web_search", boom)
    with pytest.raises(llm.SearchUnavailable, match="web search failed"):
        researcher.run("Vyntelligence", CLAIM)


def test_unreadable_pages_give_no_evidence(agent, monkeypatch):
    monkeypatch.setattr(search, "read_page", lambda url: None)
    assert researcher.run("Vyntelligence", CLAIM) == []


def test_search_off_is_respected(agent, monkeypatch):
    monkeypatch.setattr(llm, "SEARCH_ENABLED", False)
    with pytest.raises(llm.SearchUnavailable, match="SEARCH=off"):
        researcher.run("Vyntelligence", CLAIM)


def test_no_results_is_not_a_failure(monkeypatch):
    class Empty(Exception):
        pass

    class FakeDDGS:
        def text(self, q, max_results=5):
            raise Empty("No results found.")

    import ddgs
    monkeypatch.setattr(ddgs, "DDGS", FakeDDGS)
    monkeypatch.setattr(search, "PAUSE_S", 0)
    assert search.web_search("anything") == []
