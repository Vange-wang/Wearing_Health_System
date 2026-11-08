"""Durable user intent. Missing/corrupt installed state never enables work."""
import json
import math
from .state import atomic_json

class IntentStore:
    def __init__(self,paths,*,fixture=False):
        self.path=paths.state_dir/'intent.json' if hasattr(paths,'state_dir') else None
        self.valid=False;self.error=None
        try:
            if self.path is None or fixture and not self.path.exists():
                self.value={'schema_version':1,'enabled':True,'intent_generation':0,'start_generation':0,'operations':[]};self.valid=True;return
            if self.path.stat().st_size>131072:raise ValueError()
            value=json.loads(self.path.read_text(encoding='utf-8'))
            fields={'schema_version','enabled','intent_generation','start_generation','operations'}
            if (set(value) not in (fields,fields|{'manual_not_before'}) or value['schema_version']!=1
                or type(value['enabled']) is not bool or type(value['intent_generation']) is not int
                or value['intent_generation']<0 or type(value['start_generation']) is not int
                or not 0<=value['start_generation']<=value['intent_generation']
                or not isinstance(value['operations'],list) or len(value['operations'])>256):raise ValueError()
            for operation in value['operations']:
                if (not isinstance(operation,dict) or set(operation)!={'id','command','sequence','state'}
                    or not isinstance(operation['id'],str) or not 1<=len(operation['id'])<=64
                    or operation['command'] not in ('ensure','retry','stop','startup') or type(operation['sequence']) is not int
                    or operation['sequence']<1 or operation['state'] not in ('queued','completed','interrupted')):raise ValueError()
            cooldown=value.get('manual_not_before',0)
            if type(cooldown) not in (int,float) or not math.isfinite(cooldown) or cooldown<0:raise ValueError()
            value['manual_not_before']=cooldown
            value['operations']=[dict(op,state='interrupted') if op['state']=='queued' else op for op in value['operations']]
            self.value=value;self.valid=True
        except (OSError,ValueError,TypeError):
            self.value={'schema_version':1,'enabled':False,'intent_generation':0,'start_generation':0,'operations':[]};self.error='intent_missing_or_invalid'
    def commit(self,enabled,secure=None,operation=None,manual_not_before=None):
        if not self.valid:raise ValueError('intent_requires_installation_repair')
        generation=self.value['intent_generation']+1
        start=generation if enabled and not self.value['enabled'] else self.value['start_generation']
        operations=list(self.value['operations'])
        if operation:operations=(operations+[operation])[-256:]
        value=dict(schema_version=1,enabled=enabled,intent_generation=generation,start_generation=start,operations=operations,
                   manual_not_before=self.value.get('manual_not_before',0) if manual_not_before is None else manual_not_before)
        if self.path is not None:atomic_json(self.path,value,secure=secure)
        self.value=value
        return value
    def alias(self,operation,active,secure=None):
        # Pin the canonical active operation independently of alias eviction.
        others=[op for op in self.value['operations'] if op['id'] not in (active['id'],operation['id'])]
        value=dict(self.value,operations=[dict(active)]+(others+[operation])[-255:])
        if self.path is not None:atomic_json(self.path,value,secure=secure)
        self.value=value
    def finish(self,sequence,secure=None):
        value=dict(self.value,operations=[dict(op,state='completed') if op['sequence']<=sequence and op['state']!='interrupted' else dict(op) for op in self.value['operations']])
        if self.path is not None:atomic_json(self.path,value,secure=secure)
        self.value=value
