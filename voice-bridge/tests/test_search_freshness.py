from datetime import datetime
import httpx
from app import voice_web_search as ws
from app.weather_intent import classify


def test_news_does_not_ground_today_in_archived_or_undated_pages(monkeypatch):
    now = datetime(2026, 11, 8, 2, tzinfo=ws.SEARCH_ZONE)
    def respond(request):
        import json
        payload = json.loads(request.content)
        assert payload["topic"] == "news" and payload["time_range"] == "day"
        items = [
            {"url": "https://example.org/a", "published_date": stamp, "content": "新闻"}
            for stamp in ("2026-10-04", None, "2026-11-07T17:00:00Z", "2026-11-08T16:00:00Z")
        ]
        return httpx.Response(200, json={"results": items})
    monkeypatch.setattr(ws, "credential", lambda: "test")
    monkeypatch.setattr(ws, "cancellable_transport", lambda: httpx.MockTransport(respond))
    pages = ws.search_pages("公开主题", since=now.date(), now=now)
    assert [p["published_date"] for p in pages] == ["2026-11-08"]


def test_weather_chicago_explicit_and_followup():
    history = [{"role": "assistant", "content": "北京当前天气模型估计约8摄氏度。"}]
    assert classify("帮我联网查一下芝加哥今天的天气", (), allow_general=True) == "芝加哥"
    assert classify("那芝加哥呢", (), history, allow_general=True) == "芝加哥"
    assert classify("那芝加哥呢", (), (), allow_general=True) is None


def test_latest_public_release_is_read_only():
    from app.voice_v2_service import is_write_request
    assert not is_write_request("今天发布了什么新闻")
    assert is_write_request("帮我发布今天的新闻")
