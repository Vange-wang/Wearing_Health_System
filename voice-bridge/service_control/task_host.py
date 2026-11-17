"""One least-privilege Task Scheduler host. Never register/migrate implicitly."""
from pathlib import Path
import json,subprocess,xml.etree.ElementTree as ET
from .identity import base_interpreter,normal
TIME_BOUNDARY='2026-01-01T00:00:00+08:00'

def definition(paths):
    voice=paths.project/'voice-bridge';python=voice/'venv/Scripts/pythonw.exe'
    if not python.is_absolute() or not python.is_file():raise ValueError('core_interpreter_unverified')
    return dict(name='VoiceControl-'+paths.scope,executable=str(python),arguments='-B "'+str(voice/'service_control.py')+'" --core',
                working_directory=str(voice),sid=paths.sid)

def xml_text(paths):
    spec=definition(paths);ns='http://schemas.microsoft.com/windows/2004/02/mit/task'
    root=ET.Element('Task',version='1.4',xmlns=ns)
    triggers=ET.SubElement(root,'Triggers');trigger=ET.SubElement(triggers,'LogonTrigger')
    ET.SubElement(trigger,'Enabled').text='true';ET.SubElement(trigger,'UserId').text=spec['sid']
    periodic=ET.SubElement(triggers,'TimeTrigger')
    repetition=ET.SubElement(periodic,'Repetition');ET.SubElement(repetition,'Interval').text='PT1M'
    ET.SubElement(periodic,'StartBoundary').text=TIME_BOUNDARY
    ET.SubElement(periodic,'Enabled').text='true'
    principals=ET.SubElement(root,'Principals');principal=ET.SubElement(principals,'Principal',id='CurrentUser')
    for k,v in [('UserId',spec['sid']),('LogonType','InteractiveToken'),('RunLevel','LeastPrivilege')]:ET.SubElement(principal,k).text=v
    settings=ET.SubElement(root,'Settings')
    for k,v in [('MultipleInstancesPolicy','IgnoreNew'),('DisallowStartIfOnBatteries','false'),('StopIfGoingOnBatteries','false'),('StartWhenAvailable','true'),('RunOnlyIfIdle','false'),('RunOnlyIfNetworkAvailable','false'),('AllowStartOnDemand','true'),('Enabled','true'),('Hidden','true'),('ExecutionTimeLimit','PT0S'),('UseUnifiedSchedulingEngine','true')]:ET.SubElement(settings,k).text=v
    retry=ET.SubElement(settings,'RestartOnFailure');ET.SubElement(retry,'Interval').text='PT1M';ET.SubElement(retry,'Count').text='3'
    actions=ET.SubElement(root,'Actions',Context='CurrentUser');action=ET.SubElement(actions,'Exec')
    for k,v in [('Command',spec['executable']),('Arguments',spec['arguments']),('WorkingDirectory',spec['working_directory'])]:ET.SubElement(action,k).text=v
    return ET.tostring(root,encoding='unicode')

def start_verified_task(paths):
    import time,uuid
    from .state import atomic_json
    from .windows import Security
    spec=definition(paths);spec['expected_xml']=xml_text(paths);identifier=uuid.uuid4().hex
    security=Security(paths.sid)
    receipt=dict(id=identifier,requested_at=time.time(),stage='task_requested',error=None)
    target=paths.state_dir/'task-request.json'
    script=r'''$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new();$stage='read_request'
    function Resolve-TaskSid([string]$identity) {
      if([string]::IsNullOrWhiteSpace($identity)){throw 'task_identity_unmapped'}
      try {
        if($identity -match '^S-[0-9]+-') { return [System.Security.Principal.SecurityIdentifier]::new($identity).Value }
        return [System.Security.Principal.NTAccount]::new($identity).Translate([System.Security.Principal.SecurityIdentifier]).Value
      } catch { throw 'task_identity_unmapped' }
    }
    function Normalize-TaskXml([string]$xml,[string]$sid) {
      $service=New-Object -ComObject Schedule.Service;$service.Connect()
      $definition=$service.NewTask(0);$definition.XmlText=$xml
      $principal=Resolve-TaskSid $definition.Principal.UserId
      if($principal -ne $sid){throw 'task_identity_mismatch'}
      $definition.Principal.UserId=$principal
      foreach($trigger in $definition.Triggers) {
        if($trigger.Type -eq 9) {
          $triggerSid=Resolve-TaskSid $trigger.UserId
          if($triggerSid -ne $sid){throw 'task_identity_mismatch'}
          $trigger.UserId=$triggerSid
        } elseif($trigger.Type -ne 1){throw 'unexpected_task_trigger'}
      }
      return [xml]$definition.XmlText
    }
    function Canonical-TaskNode($node) {
      $attributes=@($node.Attributes | ForEach-Object { $_.Name+'='+$_.Value } | Sort-Object)
      $children=@($node.ChildNodes | Where-Object NodeType -eq Element | ForEach-Object { Canonical-TaskNode $_ } | Sort-Object)
      $leaf=if($children.Count -eq 0){$node.InnerText}else{''}
      return (@($node.NamespaceURI,$node.LocalName,($attributes -join '|'),$leaf,($children -join '|')) | ConvertTo-Json -Compress -Depth 64)
    }
    try {
      $s=[Console]::In.ReadToEnd()|ConvertFrom-Json;$stage='get_definition'
      $export=Export-ScheduledTask -TaskPath '\' -TaskName $s.name
      $stage='normalize_definition'
      $x=Normalize-TaskXml $export $s.sid
      $expectedXml=Normalize-TaskXml $s.expected_xml $s.sid
      $n=[System.Xml.XmlNamespaceManager]::new($x.NameTable);$n.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
      $stage='verify_definition'
      if($x.SelectNodes('/t:Task/t:Actions/*',$n).Count -ne 1 -or $x.SelectNodes('/t:Task/t:Triggers/*',$n).Count -ne 2){throw 'task_definition_mismatch'}
      foreach($path in @('/t:Task/t:Principals/t:Principal/t:UserId','/t:Task/t:Triggers/t:LogonTrigger/t:UserId')) {
        $node=$x.SelectSingleNode($path,$n)
        if($null -eq $node -or (Resolve-TaskSid $node.InnerText) -ne $s.sid){throw 'task_identity_mismatch'}
      }
      $en=[System.Xml.XmlNamespaceManager]::new($expectedXml.NameTable);$en.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
      foreach($section in @('Actions','Principals','Triggers','Settings')) {
        $actual=$x.SelectSingleNode('/t:Task/t:'+$section,$n)
        $wanted=$expectedXml.SelectSingleNode('/t:Task/t:'+$section,$en)
        if($null -eq $actual -or $null -eq $wanted -or (Canonical-TaskNode $actual) -ne (Canonical-TaskNode $wanted)){throw 'task_definition_mismatch'}
      }
      $stage='start_task';Start-ScheduledTask -TaskPath '\' -TaskName $s.name
    } catch { @{stage=$stage;error_category=$_.Exception.GetType().Name;hresult=$_.Exception.HResult}|ConvertTo-Json -Compress;exit 1 }
    '''
    try:
        # Installed protected directory must exist; no permissive fallback.
        if not paths.state_dir.is_dir():raise OSError('task_state_not_installed')
        atomic_json(target,receipt,secure=security.secure_file)
        result=subprocess.run(['pwsh.exe','-NoLogo','-NoProfile','-Command',script],input=json.dumps(spec).encode('utf-8'),capture_output=True,timeout=8,creationflags=0x08000000)
        if result.returncode:
            try:
                error=json.loads(result.stdout.decode('utf-8-sig'))
                receipt.update(stage=error['stage'],error=error['error_category'],hresult=error['hresult'])
            except (ValueError,KeyError,UnicodeError):receipt.update(stage='task_request',error='os_failure')
            atomic_json(target,receipt,secure=security.secure_file)
            raise OSError('scheduled_task_'+receipt['stage'])
    except (OSError,subprocess.TimeoutExpired) as error:
        if receipt['error'] is None:
            receipt.update(stage='task_request_outcome_unknown',error=type(error).__name__)
            try:atomic_json(target,receipt,secure=security.secure_file)
            except OSError:pass
        raise
    finally:security.close()
