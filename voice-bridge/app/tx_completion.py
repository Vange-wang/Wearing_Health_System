"""Authenticated device evidence for digital output, never acoustic drain."""
FIELDS=('epoch','accepted_bytes','completed_bytes','write_count','fence_seq','complete_seq','descriptor_count','descriptor_mask','unknown_partial','events_lost','cancelled','session','turn','revision','generation')
def canonical_evidence(value):
    if not isinstance(value,dict) or set(value)!=set(FIELDS):raise ValueError('tx_evidence')
    for key in FIELDS[:8]:
        if type(value[key]) is not int or not 0<=value[key]<=0x7fffffffffffffff:raise ValueError('tx_evidence')
    if type(value['events_lost']) is not int or value['events_lost']!=0:raise ValueError('tx_evidence')
    if value['unknown_partial'] is not False or value['cancelled'] is not False:raise ValueError('tx_evidence')
    if not isinstance(value['session'],str) or len(value['session'])!=32:raise ValueError('tx_evidence')
    for key in ('turn','revision','generation'):
        if type(value[key]) is not int or not 0<value[key]<=0xffffffff:raise ValueError('tx_evidence')
    n=value['descriptor_count']
    if not (n==6 and value['descriptor_mask']==(1<<n)-1):raise ValueError('tx_evidence')
    if not (value['epoch']>0 and value['accepted_bytes']>0 and value['accepted_bytes']%4==0 and value['completed_bytes']==value['accepted_bytes'] and 0<value['write_count']<=value['accepted_bytes']//4):raise ValueError('tx_evidence')
    if value['complete_seq']-value['fence_seq']<n:raise ValueError('tx_evidence')
    return tuple(value[key] for key in FIELDS)
