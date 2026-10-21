"""Bounded current-weather grammar. No model, geolocation, or fuzzy city choice."""
import re
CLARIFY='你想查询哪个城市现在的天气？'
UNSUPPORTED='目前已核验的当前天气地点是新加坡、北京和上海。请明确其中一个城市；其他地点尚未完成可靠匹配，我不会猜测天气。'
_PREFIX=re.compile(r'^(?:你好[，,]?|您好[，,]?|请问|麻烦你?|请你?|能不能帮我|可以帮我|能帮我|帮我|替我|给我|我想知道|我想了解|我想查|查询一下|查询|查一下|查查|查|看一下|看看|告诉我)+')
_TIME=re.compile(r'(?:今天|现在|当前|此刻|今日)')
_SUFFIX=re.compile(r'(?:怎么样|如何|是多少|多少度|几度|什么情况|情况|状况|好不好)?(?:呢|呀|啊|吗|吧)?[？?。！!]*$')
_KNOWLEDGE=('为什么','原理','是什么','定义','区别','形成','怎么预测','如何预测','一般','通常','季节','明天','后天','昨天','下周','未来','一周')

def classify(text,cities,history=(),*,allow_general=False):
    if not isinstance(text,str) or len(text)>100:return None
    value=re.sub(r'(?<![A-Za-z])\s+|\s+(?![A-Za-z])','',text) if allow_general else re.sub(r'\s+','',text)
    if any(word in value for word in _KNOWLEDGE):return None
    if any(word in value for word in ('你能','你会','能不能','能否','可不可以')) and not any(word in value for word in ('帮我','替我','给我','请你')):return None
    # A bare city only inherits an explicit weather clarification/result from
    # the latest delivered assistant turn, never an arbitrary old intention.
    short=re.sub(r'^(?:那|在)','',value)
    short=re.sub(r'(?:的)?(?:呢|呀|啊)?[？?。！!]*$','',short)
    if allow_general and re.fullmatch(r'[\u4e00-\u9fffA-Za-z，, -]{2,40}',short):
        last=history[-1] if history else {}
        reply=last.get('content','') if last.get('role')=='assistant' else ''
        if reply==CLARIFY or reply.startswith(('这个城市有多个同名地点','暂时无法唯一匹配这个地点','请提供城市名称')):
            return short
    if short in cities:
        last=history[-1] if history else {}
        reply=last.get('content','') if last.get('role')=='assistant' else ''
        if reply in (CLARIFY,UNSUPPORTED) or any(reply.startswith(c+'当前天气模型估计') for c in cities):return short
        return None
    if not any(word in value for word in ('天气','气温','温度')):return None
    value=_PREFIX.sub('',value)
    value=re.sub(r'[，,](?:简短回答|告诉我当前温度和天气状况)[？?。！!]*$','',value)
    value=_TIME.sub('',value)
    value=re.sub(r'(天气|气温|温度)(?:怎么样|如何|是多少|多少度|几度)[，,](?:在)?',r'\1在',value)
    value=_SUFFIX.sub('',value)
    # City before weather, or explicit location after weather. Unsupported
    # locations are handled honestly without passing to a model to invent data.
    m=re.fullmatch(r'(?:在)?(?P<city>[\u4e00-\u9fffA-Za-z，, -]{0,40}?)(?:的)?(?:天气|气温|温度)',value)
    if not m:
        m=re.fullmatch(r'(?:天气|气温|温度)(?:[，,]?在|[，,])(?P<city>[\u4e00-\u9fffA-Za-z，, -]{2,40})(?:的)?',value)
    if not m:return None
    city=m.group('city')
    if city.endswith('市') and city[:-1] in cities:city=city[:-1]
    if not city or city in ('这里','这边','当地','本地','我们这','我这','你那里'):return ''
    return city if city in cities or allow_general else '?'
