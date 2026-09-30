"""Research tools with mocked HTTP (httpx.MockTransport). No network or keys needed,
except the @pytest.mark.live smoke test, which is skipped without TAVILY_API_KEY."""
import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest

from bot import config
from bot.dispatcher import dispatch
from bot.tools import research, web_utils

ARTICLE = """<html><head><title>Realtime Models Update</title>
<script>var tracking = "SHOULD NOT APPEAR";</script><style>body{color:red}</style></head>
<body><nav>Home | About | NAVIGATION LINKS</nav>
<article><h1>Realtime Models Update</h1>
<p>OpenAI released a new realtime voice model this month with lower latency and better tool calling.</p>
<p>The model supports speech to speech conversations and costs less than the previous version.</p>
<p>Developers can connect over WebSocket or WebRTC and stream audio in both directions.</p>
</article><footer>Copyright FOOTER TEXT</footer></body></html>"""

TAVILY_OK = {
    "results": [
        {"title": "Realtime update", "url": "https://www.example.com/a", "content": "x" * 500,
         "published_date": "2026-09-20"},
        {"title": "Second", "url": "https://news.site.org/b", "content": "short", "published_date": None},
    ]
}
BRAVE_OK = {"web": {"results": [{"title": "Brave hit", "url": "https://brave.example/c",
                                 "description": "from brave", "age": "2 days ago"}]}}


class FakeWeb:
    """Routes requests by URL; records every call."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.routes: dict[str, callable] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = str(request.url)
        for prefix, respond in self.routes.items():
            if url.startswith(prefix):
                return respond(request)
        return httpx.Response(404, text="not found")


@pytest.fixture
def web(tmp_path, monkeypatch):
    fake = FakeWeb()
    monkeypatch.setattr(web_utils, "_client", httpx.Client(transport=httpx.MockTransport(fake.handler), follow_redirects=True))
    monkeypatch.setattr(web_utils, "RETRY_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(web_utils, "last_web_url", None)
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "test-bot.log")
    monkeypatch.setattr(config, "TAVILY_API_KEY", "tvly-test")
    monkeypatch.setattr(config, "BRAVE_API_KEY", "brave-test")
    web_utils.cache_clear()
    yield fake
    web_utils.cache_clear()


def call(name: str, **args) -> dict:
    return json.loads(asyncio.run(dispatch(name, json.dumps(args))))


def html_page(body: str = ARTICLE, status: int = 200):
    return lambda req: httpx.Response(status, text=body, headers={"content-type": "text/html; charset=utf-8"})


# --- web_search -------------------------------------------------------------------

def test_tavily_results_mapped(web):
    web.routes[research.TAVILY_URL] = lambda req: httpx.Response(200, json=TAVILY_OK)
    r = call("web_search", query="realtime models", topic="news", recency_days=7)
    assert r["ok"] and r["provider"] == "tavily"
    first = r["results"][0]
    assert first == {
        "n": 1, "title": "Realtime update", "url": "https://www.example.com/a",
        "source": "example.com", "snippet": "x" * 300, "published": "2026-09-20",
    }
    assert r["results"][1]["source"] == "news.site.org"
    sent = json.loads(web.calls[0].content)
    assert sent["topic"] == "news" and sent["days"] == 7 and sent["search_depth"] == "basic"
    assert web.calls[0].headers["authorization"] == "Bearer tvly-test"


def test_tavily_500_falls_back_to_brave(web):
    web.routes[research.TAVILY_URL] = lambda req: httpx.Response(500)
    web.routes[research.BRAVE_URL] = lambda req: httpx.Response(200, json=BRAVE_OK)
    r = call("web_search", query="anything", recency_days=7)
    assert r["ok"] and r["provider"] == "brave"
    assert r["results"][0]["snippet"] == "from brave" and r["results"][0]["published"] == "2 days ago"
    tavily_calls = [c for c in web.calls if str(c.url).startswith(research.TAVILY_URL)]
    assert len(tavily_calls) == 2  # one retry on 5xx
    brave_call = next(c for c in web.calls if str(c.url).startswith(research.BRAVE_URL))
    assert brave_call.headers["x-subscription-token"] == "brave-test"
    assert brave_call.url.params["freshness"] == "pw"


def test_no_tavily_key_uses_brave(web, monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    web.routes[research.BRAVE_URL] = lambda req: httpx.Response(200, json=BRAVE_OK)
    assert call("web_search", query="q")["provider"] == "brave"


def test_no_keys_names_env_vars(web, monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "")
    monkeypatch.setattr(config, "BRAVE_API_KEY", "")
    r = call("web_search", query="q")
    assert r["ok"] is False
    assert "TAVILY_API_KEY" in r["error"] and "BRAVE_API_KEY" in r["error"] and ".env" in r["error"]
    assert web.calls == []


def test_both_providers_fail_is_readable(web):
    web.routes[research.TAVILY_URL] = lambda req: httpx.Response(401)
    web.routes[research.BRAVE_URL] = lambda req: httpx.Response(403)
    r = call("web_search", query="q")
    assert r["ok"] is False and "tavily" in r["error"] and "brave" in r["error"]


def test_duplicate_urls_collapsed(web):
    dupes = {"results": [
        {"title": "A", "url": "https://cnbc.com/2026/x.html", "content": "1"},
        {"title": "A again", "url": "https://www.cnbc.com/2026/x.html/", "content": "2"},
        {"title": "B", "url": "https://other.com/y", "content": "3"},
    ]}
    web.routes[research.TAVILY_URL] = lambda req: httpx.Response(200, json=dupes)
    r = call("web_search", query="dupes")
    assert [x["title"] for x in r["results"]] == ["A", "B"] and [x["n"] for x in r["results"]] == [1, 2]


def test_zero_results_is_ok(web):
    web.routes[research.TAVILY_URL] = lambda req: httpx.Response(200, json={"results": []})
    r = call("web_search", query="nothing matches")
    assert r["ok"] is True and r["results"] == []


def test_search_is_cached(web):
    web.routes[research.TAVILY_URL] = lambda req: httpx.Response(200, json=TAVILY_OK)
    call("web_search", query="cache me")
    call("web_search", query="Cache me")
    assert len(web.calls) == 1


def test_timeout_retries_once_then_falls_back(web):
    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)

    web.routes[research.TAVILY_URL] = slow
    web.routes[research.BRAVE_URL] = lambda req: httpx.Response(200, json=BRAVE_OK)
    r = call("web_search", query="q")
    assert r["provider"] == "brave"
    assert sum(str(c.url).startswith(research.TAVILY_URL) for c in web.calls) == 2


# --- scrape_page -----------------------------------------------------------------

def test_scrape_clean_text_with_banner(web):
    web.routes["https://example.com/article"] = html_page()
    r = call("scrape_page", url="https://example.com/article")
    assert r["ok"] and r["title"] == "Realtime Models Update" and r["site"] == "example.com"
    assert r["text"].startswith(web_utils.UNTRUSTED_BANNER)
    assert "lower latency" in r["text"]
    for junk in ("SHOULD NOT APPEAR", "NAVIGATION LINKS", "color:red"):
        assert junk not in r["text"]
    assert r["truncated"] is False
    assert web_utils.last_web_url == "https://example.com/article"


def test_scrape_long_page_focuses_on_question(web):
    filler = "".join(f"<p>Paragraph {i} is about gardening, tomatoes and soil moisture levels today.</p>" for i in range(80))
    key = "<p>The quantum battery prototype stores energy using entangled qubits in the lab.</p>"
    page = f"<html><head><title>Mixed</title></head><body><article><p>Intro paragraph for the page.</p>{filler}{key}{filler}</article></body></html>"
    web.routes["https://example.com/long"] = html_page(page)
    r = call("scrape_page", url="https://example.com/long", focus="quantum battery", max_chars=1000)
    text = r["text"].removeprefix(web_utils.UNTRUSTED_BANNER)
    assert r["ok"] and r["truncated"] is True and r["original_chars"] > 1000
    assert len(text) <= 1000
    assert "quantum battery" in text and text.startswith("Intro paragraph")


def test_scrape_403_is_ok_false(web):
    web.routes["https://blocked.com"] = html_page(status=403)
    r = call("scrape_page", url="https://blocked.com/x")
    assert r["ok"] is False and "403" in r["error"]


def test_scrape_pdf_is_helpful(web):
    web.routes["https://example.com/doc.pdf"] = lambda req: httpx.Response(
        200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"})
    r = call("scrape_page", url="https://example.com/doc.pdf")
    assert r["ok"] is False and "PDF" in r["error"] and "run_shell" in r["error"]


def test_scrape_empty_page(web):
    web.routes["https://example.com/js"] = html_page("<html><body><div id=app></div></body></html>")
    r = call("scrape_page", url="https://example.com/js")
    assert r["ok"] is False and "no readable text" in r["error"]


@pytest.mark.parametrize("bad", ["file:///C:/Windows/win.ini", "javascript:alert(1)", "ftp://x.com", "not a url"])
def test_scrape_rejects_non_web_urls(web, bad):
    r = call("scrape_page", url=bad)
    assert r["ok"] is False and web.calls == []


# --- open_url --------------------------------------------------------------------

def test_open_url_valid(monkeypatch, web):
    opened = []
    monkeypatch.setattr(research.webbrowser, "open", lambda url: opened.append(url) or True)
    assert call("open_url", url="https://example.com")["ok"] and opened == ["https://example.com"]


@pytest.mark.parametrize("bad", ["file:///C:/Windows/win.ini", "javascript:alert(1)", "C:\\Users"])
def test_open_url_rejects_unsafe(monkeypatch, web, bad):
    opened = []
    monkeypatch.setattr(research.webbrowser, "open", lambda url: opened.append(url) or True)
    assert call("open_url", url=bad)["ok"] is False and opened == []


# --- research (one-shot) -----------------------------------------------------------

def test_research_skips_failed_page_and_uses_next(web):
    results = {"results": [
        {"title": "Blocked", "url": "https://blocked.com/1", "content": "a"},
        {"title": "Good A", "url": "https://a.com/1", "content": "b"},
        {"title": "Good B", "url": "https://b.com/1", "content": "c"},
        {"title": "Good C", "url": "https://c.com/1", "content": "d"},
    ]}
    web.routes[research.TAVILY_URL] = lambda req: httpx.Response(200, json=results)
    web.routes["https://blocked.com"] = html_page(status=403)
    for site in ("a", "b", "c"):
        web.routes[f"https://{site}.com"] = html_page()
    r = call("research", question="realtime voice model latency", max_sources=2)
    assert r["ok"] and [s["site"] for s in r["sources"]] == ["a.com", "b.com"]
    assert [s["n"] for s in r["sources"]] == [1, 2] and r["skipped"] == 1
    assert all(s["excerpt"].startswith(web_utils.UNTRUSTED_BANNER) for s in r["sources"])


def test_research_thin_page_uses_search_snippet(web):
    snippet = "OpenAI demoed three new realtime audio models: GPT-Realtime-2, Translate, and Whisper."
    web.routes[research.TAVILY_URL] = lambda req: httpx.Response(
        200, json={"results": [{"title": "Video", "url": "https://video.com/w", "content": snippet}]})
    menu = "<html><head><title>Video</title></head><body>" + "<p>About Press Copyright Contact Terms Privacy Policy Safety</p>" * 3 + "</body></html>"
    web.routes["https://video.com"] = html_page(menu)
    r = call("research", question="realtime audio models", max_sources=1)
    assert r["ok"] and r["sources"][0]["excerpt"] == web_utils.UNTRUSTED_BANNER + snippet


def test_research_all_pages_fail(web):
    web.routes[research.TAVILY_URL] = lambda req: httpx.Response(
        200, json={"results": [{"title": "x", "url": "https://blocked.com/1", "content": ""}]})
    web.routes["https://blocked.com"] = html_page(status=403)
    r = call("research", question="q")
    assert r["ok"] is False and "couldn't read" in r["error"]


# --- audit trail ------------------------------------------------------------------

def test_log_links_shell_call_to_last_web_page(web, tmp_path):
    web.routes["https://example.com/article"] = html_page()
    call("scrape_page", url="https://example.com/article")
    call("list_dir", path=str(tmp_path))
    call("run_shell", command="echo hi", cwd=str(tmp_path))
    entries = [json.loads(line) for line in config.LOG_FILE.read_text(encoding="utf-8").splitlines()]
    assert "after_web_url" not in entries[1]
    assert entries[2]["after_web_url"] == "https://example.com/article"


def test_focus_excerpt_short_text_untouched():
    assert web_utils.focus_excerpt("short text", "x", 100) == ("short text", False)


# --- live smoke test (skipped by default) --------------------------------------------

@pytest.mark.live
@pytest.mark.skipif(not os.getenv("TAVILY_API_KEY"), reason="TAVILY_API_KEY not set")
def test_live_tavily_search():
    web_utils.cache_clear()
    r = json.loads(research.web_search("python 3.13 release date", max_results=3))
    assert r["ok"] and r["results"], r


# --- Fix 1: deep research end to end ----------------------------------------------------------

from bot import jobs, llm  # noqa: E402


def deep_llm(monkeypatch, calls: list | None = None):
    def fake(prompt, **kw):
        if calls is not None:
            calls.append(prompt)
        if "JSON array" in kw.get("instructions", ""):
            return '["query one", "query two"]'
        return "SPOKEN SUMMARY: Companies disagree on pace.\n\n## Summary\nThey disagree [1]."
    monkeypatch.setattr(llm, "complete", fake)


def tavily_results(per_query: dict):
    def respond(req):
        q = json.loads(req.content)["query"]
        return httpx.Response(200, json={"results": per_query[q]})
    return respond


def test_deep_research_mixed_pages_completes_from_readable_ones(web, monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    calls: list = []
    deep_llm(monkeypatch, calls)
    web.routes[research.TAVILY_URL] = tavily_results({
        "query one": [
            {"title": "Blocked A", "url": "https://blocked.com/1", "content": "short"},
            {"title": "Good A", "url": "https://good.com/1", "content": "x"},
        ],
        "query two": [
            {"title": "Blocked, but indexed", "url": "https://cf.com/2", "content": "s",
             "raw_content": "Official statement: the company supports AI governance rules. " * 10},
            {"title": "Broken", "url": "https://broken.com/3", "content": "tiny"},
        ],
    })
    web.routes["https://blocked.com"] = html_page(status=403)
    web.routes["https://cf.com"] = html_page(status=403)
    web.routes["https://broken.com"] = html_page(status=500)
    web.routes["https://good.com"] = html_page()

    caplog.set_level("INFO", logger="bot.tools.research")
    r = json.loads(research.deep_research("AI governance", "news", 14))
    assert r["ok"], r
    sites = [s.split(":")[0] for s in r["sources"]]
    assert "good.com" in sites and "cf.com" in sites  # direct read + search-index fallback
    assert "blocked.com" not in sites and "broken.com" not in sites
    assert Path(r["path"]).exists() and r["file_name"].startswith("research-")
    report = Path(r["path"]).read_text(encoding="utf-8")
    assert "## Sources" in report and "https://good.com/1" in report and "https://cf.com/2" in report
    assert "skipped https://blocked.com/1" in caplog.text  # each failure logged with its reason
    sent = json.loads(web.calls[0].content)
    assert sent["include_raw_content"] is True


def test_deep_research_all_pages_fail_gives_clear_reason(web, monkeypatch, caplog):
    deep_llm(monkeypatch)
    web.routes[research.TAVILY_URL] = tavily_results({
        "query one": [{"title": "A", "url": "https://blocked.com/1", "content": "x"}],
        "query two": [{"title": "B", "url": "https://blocked.org/2", "content": "y"}],
    })
    web.routes["https://blocked.com"] = html_page(status=403)
    web.routes["https://blocked.org"] = html_page(status=403)
    caplog.set_level("INFO")
    r = json.loads(research.deep_research("q"))
    assert r["ok"] is False and "couldn't read any of the 2 pages" in r["error"] and "403" in r["error"]
    assert "deep research read 0 of 2 pages" in caplog.text


def test_deep_research_crash_logs_traceback(web, monkeypatch, caplog):
    deep_llm(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("kaboom inside reading")

    monkeypatch.setattr(research, "_read_sources", boom)
    web.routes[research.TAVILY_URL] = tavily_results({
        "query one": [{"title": "A", "url": "https://a.com/1", "content": "x"}], "query two": []})
    r = json.loads(research.deep_research("q"))
    assert r["ok"] is False and "kaboom" in r["error"]
    assert "deep research crashed" in caplog.text and "Traceback" in caplog.text


def test_planner_uses_today_and_no_site_operators():
    text = research._plan_instructions()
    assert "no site:" in text and f"{__import__('datetime').datetime.now().year}" in text


def test_interleave_spreads_queries_and_caps_sites():
    q1 = [{"url": f"https://apnews.com/{i}"} for i in range(5)]
    q2 = [{"url": f"https://other{i}.com/x"} for i in range(3)]
    picked = [r["url"] for r in research._interleave([q1, q2])]
    assert picked[:2] == ["https://apnews.com/0", "https://other0.com/x"]
    assert sum("apnews.com" in u for u in picked) == research.DEEP_PER_SITE


def run_in_loop(coro_fn):
    async def main():
        manager = jobs.JobManager()
        notes = []

        async def notify(n):
            notes.append(n)

        manager.attach(asyncio.get_running_loop(), notify)
        return await coro_fn(manager, notes)

    return asyncio.run(main())


def test_one_deep_request_creates_exactly_one_job(web, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    deep_llm(monkeypatch)
    web.routes[research.TAVILY_URL] = tavily_results({
        "query one": [{"title": "Good", "url": "https://good.com/1", "content": "x"}], "query two": []})
    web.routes["https://good.com"] = html_page()

    async def scenario(manager, notes):
        import bot.tools.jobs_tools as jt
        monkeypatch.setattr(jobs, "manager", manager)
        monkeypatch.setattr(jt, "manager", manager)
        # Exactly what the model did in bot.log: wrap deep research in start_background_job.
        started = json.loads(await dispatch("start_background_job", json.dumps(
            {"kind": "research", "args": {"question": "AI governance", "mode": "deep", "topic": "news"}})))
        while any(j.status == "running" for j in manager.jobs.values()):
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.05)
        return started, manager, notes

    started, manager, notes = run_in_loop(scenario)
    assert started["status"] == "started" and "STARTED, not finished" in started["note"]
    assert list(manager.jobs) == [started["job_id"]]  # one request, one job
    job = manager.jobs[started["job_id"]]
    assert job.kind == "deep_research" and job.status == "done"
    assert len(notes) == 1 and "That's done:" in notes[0] and "research-" in notes[0]
