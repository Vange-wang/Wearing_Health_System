"""A5 current-weather model estimate; no search snippets or LLM calls."""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
import json
import logging
import math
from pathlib import Path
import re
import threading
import time
import httpx
from .http_stream_transport import current_scope
from .weather_dns import weather_transport
from .llm import LLMBase
from .weather_intent import classify, CLARIFY, UNSUPPORTED
from .weather_location import resolve_location, LocationClarification
from .stream_resources import OwnedSyncStream
from .http_stream_transport import CancelScope

class SearchTimeout(Exception):pass
class SearchCancelled(Exception):pass

class _JoinedScope:
    def __init__(self,parent):
        self.parent=parent;self.streams={};self.lock=threading.Lock();self.aborted=False
    @property
    def cancelled(self):return self.aborted or (self.parent is not None and self.parent.cancelled)
    def register(self,stream,lineage=None):
        key=stream if lineage is None else lineage
        with self.lock:
            if self.aborted:raise SearchTimeout()
            self.parent.register(stream,lineage)
            self.streams[key]=stream
    def unregister(self,lineage):
        if self.parent is not None:self.parent.unregister(lineage)
        with self.lock:self.streams.pop(lineage,None)
    def abort(self):
        with self.lock:self.aborted=True;keys=list(self.streams)
        self.parent.abort_registered(keys)
    def detach(self):
        with self.lock:keys=list(self.streams);self.streams.clear()
        for key in keys:
            if self.parent is not None:self.parent.unregister(key)

class SearchDeadline:
    def __enter__(self):
        self.parent=current_scope.get() or CancelScope()
        self.scope=_JoinedScope(self.parent)
        self.token=current_scope.set(self.scope)
        self.end=time.monotonic()+15.0
        self.lock=threading.Lock();self.active=True;self.expired=False
        def expire():
            with self.lock:
                if not self.active:return
                self.expired=True
            self.scope.abort()
        self.timer=threading.Timer(max(0,self.end-time.monotonic()),expire)
        self.timer.name='weather-deadline';self.timer.daemon=True;self.timer.start()
        return self
    def check(self):
        if self.parent is not None and self.parent.cancelled:raise SearchCancelled()
        if self.expired or time.monotonic()>=self.end:raise SearchTimeout()
    def __exit__(self,kind,value,tb):
        with self.lock:self.active=False
        self.timer.cancel();self.timer.join()
        try:
            if kind is None:self.check()
        finally:
            self.scope.detach();current_scope.reset(self.token)


CITIES={'新加坡':(1.29,103.85),'北京':(39.9042,116.4074),'上海':(31.2304,121.4737)}
ZONE=timezone(timedelta(hours=8))
CONDITIONS=json.loads(Path(__file__).with_name('weather_conditions.json').read_text(encoding='utf-8'))
URL='https://api.open-meteo.com/v1/forecast'
FAILURE='暂时没能取得可靠的当前天气数据，请稍后再试。'
logger=logging.getLogger('voice-bridge.weather')

class WeatherFailure(Exception):
    def __init__(self,category):self.category=category;super().__init__(category)

class WeatherSearch(ABC):
    @abstractmethod
    def search(self,city,now):pass

def finite(value):return type(value) in (float,int) and math.isfinite(value)

def observation(data,city,now,coordinates=None):
    try:
        lat,lon=coordinates if coordinates is not None else CITIES[city];a=data['latitude'];b=data['longitude']
        # Grid-centre tolerance: at most about 11 km per axis.
        if not finite(a) or not finite(b) or abs(a-lat)>0.1 or abs(b-lon)>0.1:raise ValueError()
        if data['timezone']!='Asia/Singapore' or type(data['utc_offset_seconds']) is not int or data['utc_offset_seconds']!=28800:raise ValueError()
        units=data['current_units']
        if any(units.get(k)!=v for k,v in {'time':'iso8601','temperature_2m':'°C','weather_code':'wmo code','is_day':''}.items()):raise ValueError()
        current=data['current'];temp=current['temperature_2m'];code=current['weather_code'];day=current['is_day']
        if not finite(temp) or not -90<=temp<=65 or type(code) is not int or str(code) not in CONDITIONS or type(day) is not int or day not in (0,1):raise ValueError()
        stamp=current['time']
        if not isinstance(stamp,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}',stamp):raise ValueError()
        updated=datetime.strptime(stamp,'%Y-%m-%dT%H:%M').replace(tzinfo=ZONE)
        local=now.astimezone(ZONE);age=(local-updated).total_seconds()
        if updated.date()!=local.date() or not 0<=age<=3600:raise ValueError()
        return {'city':city,'temp_c':temp,'condition':CONDITIONS[str(code)],'time':stamp,'source':'Open-Meteo','model_estimate':True}
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError):
        raise WeatherFailure('invalid_data') from None

class OpenMeteoWeatherSearch(WeatherSearch):
    def search(self,city,now):
        deadline=None
        try:
            with SearchDeadline() as deadline:
                deadline.check();coordinates=CITIES.get(city);label=city
                with httpx.Client(trust_env=False,verify=True,follow_redirects=False,
                    timeout=httpx.Timeout(15,connect=3),transport=weather_transport()) as client:
                    if coordinates is None:label,coordinates=resolve_location(client,deadline,city)
                    lat,lon=coordinates
                    with client.stream('GET',URL,params={'latitude':lat,'longitude':lon,
                        'current':'temperature_2m,weather_code,is_day','timezone':'Asia/Singapore','forecast_days':1}) as response:
                        response.raise_for_status();body=bytearray()
                        for chunk in response.iter_bytes():
                            deadline.check();body.extend(chunk)
                            if len(body)>64000:raise WeatherFailure('invalid_data')
                        data=json.loads(body)
                deadline.check();return observation(data,label,now,coordinates)
        except (SearchCancelled,LocationClarification):raise
        except Exception as exc:
            parent=deadline.parent if deadline is not None else current_scope.get()
            if parent is not None and parent.cancelled:raise SearchCancelled() from None
            if isinstance(exc,(SearchTimeout,httpx.TimeoutException)) or (deadline is not None and deadline.expired):category='timeout'
            elif isinstance(exc,httpx.HTTPStatusError):category='http_status'
            elif isinstance(exc,httpx.NetworkError):category='network_error'
            elif isinstance(exc,WeatherFailure):category=exc.category
            else:category='invalid_data'
            raise WeatherFailure(category) from None

def request_pattern(cities):
    choices='|'.join(re.escape(city) for city in cities)
    return re.compile(r'(?:请|帮我)?(?:查询|查一下|查查|看看)?('+choices+r')?(?:今天|现在|当前)?(?:的)?(?:天气|气温)(?:怎么样|如何|是多少)?(?:[，,](?:简短回答|告诉我当前温度和天气状况))?[？?。！!]?')

class WeatherRouteCandidate(LLMBase):
    name='hermes'
    def __init__(self,hermes,lightweight,search,*,enabled=False,clock=None,cities=None,general_locations=False):
        self.hermes=hermes;self.lightweight=lightweight;self.search=search;self.enabled=bool(enabled)
        self.general_locations=general_locations
        self.cities=tuple(CITIES if cities is None else cities)
        if not self.cities or any(city not in CITIES for city in self.cities):raise ValueError('Unsupported weather city')
        self.request=request_pattern(self.cities);self.clock=clock or (lambda:datetime.now(ZONE))
        if hermes.conversation_history is not lightweight.conversation_history:raise ValueError('Shared history required')
        self.conversation_history=hermes.conversation_history;self._weather_error=False
    @property
    def model(self):return getattr(self.hermes,'model',None)
    @property
    def tools_available(self):return getattr(self.hermes,'tools_available',True)
    @property
    def last_response_model(self):return getattr(self.hermes,'last_response_model',None)
    @property
    def last_call_ok(self):
        states=[getattr(self.hermes,'last_call_ok',None),getattr(self.lightweight,'last_call_ok',None)]
        if self._weather_error or any(x is False for x in states):return False
        return True if any(x is True for x in states) else None
    def chat(self,text):return self.hermes.chat(text)
    def _intent(self,text):
        history=()
        if len(text)<20 and any(city in text for city in self.cities):
            history=self.conversation_history.snapshot()
        return classify(text,self.cities,history,allow_general=self.general_locations) if self.enabled else None
    def handles_current_weather(self,text):return self._intent(text) is not None
    def stream_chat(self,text):
        city=self._intent(text)
        if city is None:return self.hermes.stream_chat(text)
        cancelled=threading.Event();collected=[];successful=[False]
        stats={'tool_seen':False,'weather_status':'pending'}
        class Response:
            def close(self):cancelled.set()
        def check():
            scope=current_scope.get()
            if cancelled.is_set() or (scope is not None and scope.cancelled):raise SearchCancelled()
        def content():
            check()
            if city in ('','?'):
                answer=CLARIFY if city=='' else UNSUPPORTED;successful[0]=True;stats['weather_status']='clarification'
            else:
                start=time.perf_counter();self._weather_error=False;stats['tool_seen']=True
                try:
                    data=self.search.search(city,self.clock());check()
                    hour,minute=data['time'][11:16].split(':')
                    answer=(f"{data['city']}当前天气模型估计约{data['temp_c']:g}摄氏度，{data['condition']}。"
                            f"数据时间{int(hour)}点{int(minute)}分，来源Open-Meteo。")
                    successful[0]=True;stats['weather_status']='success'
                except SearchCancelled:raise
                except LocationClarification as exc:
                    answer=str(exc);successful[0]=True;stats['weather_status']='clarification'
                except Exception as exc:
                    check();self._weather_error=True;stats['weather_status']='failed'
                    category=exc.category if isinstance(exc,WeatherFailure) and exc.category in {'timeout','http_status','invalid_data','network_error'} else 'invalid_data'
                    stats['weather_error']=category
                    logger.warning('weather_failed category=%s',category);answer=FAILURE
                finally:stats['weather_search_ms']=round((time.perf_counter()-start)*1000,3)
            check();collected.append(answer);yield answer
        def commit():
            if successful[0]:self.conversation_history.remember(text,''.join(collected))
        return OwnedSyncStream(content(),Response(),stats,commit)
    def close(self):self.hermes.close()
