from dataclasses import replace
import json

def lease_paths(paths,role):return replace(paths,namespace=paths.namespace+'-role-'+role)

def handoff_verified(paths):
    try:
        value=json.loads((paths.state_dir/'task-host.json').read_text(encoding='utf-8'))
        return value==dict(schema_version=1,project_root=str(paths.project.resolve()),user_sid=paths.sid,
                           legacy_handoff_complete=True,role_lease=True)
    except (OSError,ValueError,TypeError):return False
