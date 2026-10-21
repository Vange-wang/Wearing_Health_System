import os
from pathlib import Path

def credential():
    value = os.environ.get('TAVILY_API_KEY')
    if value:
        return value
    # Do not deserialize the credential file or retain unrelated field values.
    with (Path.home()/'.hermes'/'.env').open('rb', buffering=0) as stream:
        name = bytearray()
        while True:
            ch = stream.read(1)
            if not ch:
                break
            if ch == b'\n':
                name.clear()
            elif ch == b'=':
                wanted = bytes(name).strip().removeprefix(b'export ').strip() == b'TAVILY_API_KEY'
                name.clear()
                if wanted:
                    return stream.readline().decode('utf-8').strip().strip('\"\'')
                while ch and ch != b'\n':
                    ch = stream.read(1)
            elif len(name) < 256:
                name.extend(ch)
    raise RuntimeError('Tavily credential unavailable')
