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


def test_weather_retries_and_rechecks_local_date_before_reuse(monkeypatch):
    from datetime import timezone, timedelta
    from app import weather
    now = datetime(2026, 11, 9, 5, 55, tzinfo=timezone.utc)
    readings = ["2026-11-08T23:45", "2026-11-09T00:00"]
    calls = []
    def forecast(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("transient")
        return httpx.Response(200, json={
            "latitude": 41.85, "longitude": -87.65, "timezone": "America/Chicago",
            "utc_offset_seconds": -21600,
            "current_units": {"time": "iso8601", "temperature_2m": "°C",
                              "weather_code": "wmo code", "is_day": ""},
            "current": {"time": readings.pop(0), "temperature_2m": 5, "weather_code": 0, "is_day": 0}})
    monkeypatch.setattr(weather, "weather_transport", lambda: httpx.MockTransport(forecast))
    monkeypatch.setattr(weather, "resolve_location", lambda *args: ("芝加哥", (41.85, -87.65)))
    client = weather.OpenMeteoWeatherSearch()
    assert client.search("芝加哥", now)["time"].endswith("23:45")
    assert client.search("芝加哥", now)["time"].endswith("23:45")
    assert client.search("芝加哥", now + timedelta(minutes=6))["time"].endswith("00:00")
    assert len(calls) == 3
