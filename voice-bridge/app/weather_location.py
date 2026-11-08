"""Exact, ambiguity-preserving selection from the official geocoding API.

Contract: https://open-meteo.com/en/docs/geocoding-api . Never use result order
or population to choose between distinct exact-name places.
"""
import json,math,re
URL='https://geocoding-api.open-meteo.com/v1/search'
class LocationClarification(Exception):pass

def normal(value):
    return re.sub(r'\s+','',value).casefold().removesuffix('市')

_ADMIN_NAMES=('黑龙江','内蒙古','广东','湖南','湖北','河北','河南','山东','山西','陕西',
    '江苏','浙江','安徽','福建','江西','四川','贵州','云南','海南','辽宁','吉林','甘肃',
    '青海','广西','宁夏','新疆','西藏','北京','天津','上海','重庆','香港','澳门','台湾')
_ADMIN_SUFFIX=r'(?:壮族自治区|回族自治区|维吾尔自治区|自治区|特别行政区|省|市)?'
_ADMIN_PREFIX=re.compile(r'^('+ '|'.join(_ADMIN_NAMES) +r')(?>'+_ADMIN_SUFFIX+r')([\u4e00-\u9fff]{2,30})$')
# Verified API index spelling; selection still compares normalized name and
# supplied admin metadata. No coordinates or preferred result are hardcoded.
_SEARCH_NAMES={'长沙':'长沙市'}

def admin_normal(value):
    return re.sub(r'(?:壮族自治区|回族自治区|维吾尔自治区|自治区|特别行政区|省)$','',normal(value))

def location_parts(query):
    parts=query.replace('，',',').split(',')
    if len(parts)==1:
        match=_ADMIN_PREFIX.fullmatch(parts[0].strip())
        if match:parts=[match[2],match[1]]
    if not 1<=len(parts)<=2 or any(not re.fullmatch(r'[\u4e00-\u9fffA-Za-z -]{2,40}',p.strip()) for p in parts):
        raise LocationClarification('请提供城市名称，重名时加上省份或国家，例如“深圳，广东”。')
    return [p.strip() for p in parts]

def select_location(query,data):
    parts=location_parts(query)
    rows=data.get('results',[]) if isinstance(data,dict) else None
    if not isinstance(rows,list) or len(rows)>100:raise ValueError('invalid geocoding response')
    found={}
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('name'),str):continue
        if normal(row['name'])!=normal(parts[0]):continue
        if len(parts)==2:
            aliases=[row.get(k,'') for k in ('country','country_code','admin1')]
            qualifier=admin_normal(parts[1])
            if not any(isinstance(a,str) and admin_normal(a)==qualifier for a in aliases):continue
        lat,lon=row.get('latitude'),row.get('longitude')
        if type(lat) not in (int,float) or type(lon) not in (int,float) or not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:continue
        if not isinstance(row.get('feature_code'),str) or not row['feature_code'].startswith('PPL'):continue
        label='，'.join(str(row.get(k,'')) for k in ('name','admin1','country') if row.get(k))
        if len(label)>100 or any(ord(c)<32 for c in label):continue
        found[(round(lat,4),round(lon,4))]=(label,(lat,lon))
    if len(found)!=1:
        if found:
            labels=[value[0] for value in list(found.values())[:3]]
            raise LocationClarification('这个城市有多个同名地点：'+'；'.join(labels)+'。请补充省份或国家。')
        raise LocationClarification('暂时无法唯一匹配这个地点。请提供完整城市名，并补充省份或国家，例如“深圳，广东”。')
    return next(iter(found.values()))

def resolve_location(client,deadline,query):
    parts=location_parts(query)
    # Query once for the normalized city. Enforce the user's qualifier locally
    # so administrative suffix aliases do not depend on the API's exact filter.
    search_name=parts[0].removesuffix('市')
    search_name=_SEARCH_NAMES.get(search_name,search_name)
    with client.stream('GET',URL,params={'name':search_name,'count':100,'language':'zh','format':'json'}) as response:
        response.raise_for_status();body=bytearray()
        for chunk in response.iter_bytes():
            deadline.check();body.extend(chunk)
            if len(body)>128000:raise ValueError('geocoding response too large')
    deadline.check();return select_location(query,json.loads(body))
