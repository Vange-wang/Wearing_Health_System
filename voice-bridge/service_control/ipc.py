"""One bounded current-user/local-only request per named-pipe connection."""
import json
import threading
from .protocol import parse_request, encode_request
from .windows import Pipe, Security


class PipeServer:
    def __init__(self, paths, dispatch):
        self.paths = paths
        self.dispatch = dispatch
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run,name="control-pipe",daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        security = Security(self.paths.sid)
        first = True
        try:
            while not self.stopped.is_set():
                pipe = None
                try:
                    pipe = Pipe.server(self.paths.pipe,security,first=first)
                    first = False
                    if not pipe.connect():
                        continue
                    try:
                        request = parse_request(pipe.read())
                        reply = self.dispatch(request)
                    except (ValueError,UnicodeError,TimeoutError) as error:
                        reply = {"schema_version":1,"accepted":False,"reason":type(error).__name__}
                    pipe.write(json.dumps(reply,ensure_ascii=False,separators=(",", ":")).encode("utf-8"))
                    # Wait only for client close (or a bounded malicious peer),
                    # so closing the server cannot discard a buffered response.
                    try:pipe.read(limit=1,timeout=0.5)
                    except (OSError,ValueError,TimeoutError):pass
                except (OSError,TimeoutError):
                    self.stopped.wait(0.25)
                finally:
                    if pipe is not None:pipe.close()
        finally:
            security.close()

    def close(self):
        self.stopped.set()
        self.thread.join(4)


def request(paths, command, request_id, *, timeout=3):
    pipe = Pipe.client(paths.pipe,timeout)
    try:
        peer_pid = pipe.server_pid()
        pipe.write(encode_request(request_id,command),timeout)
        reply = json.loads(pipe.read(limit=65536,timeout=timeout).decode("utf-8"))
        if not isinstance(reply,dict) or reply.get("schema_version") != 1:
            raise ValueError("invalid control reply")
        if reply.get("request_id") not in (None,request_id):
            raise ValueError("control reply ID mismatch")
        return reply,peer_pid
    finally:
        pipe.close()
