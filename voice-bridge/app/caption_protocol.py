"""Negotiated metadata sent only after an ordinary audio frame."""
import struct
from collections import deque

CAPTION_MARKER = b'\xff\xff\xff\xff'


def encode_caption(text: str) -> bytes:
    payload = text.encode('utf-8')
    return CAPTION_MARKER + struct.pack('>Q', len(payload)) + payload


class CaptionStream:
    """Incremental viewport-sized records, no total text length restriction."""
    def __init__(self):
        self.pending = deque()

    def add(self, text):
        if text:
            self.pending.append((text, 0))

    def next_frame(self):
        if not self.pending:
            return None
        text, offset = self.pending.popleft()
        end = offset + 128  # <=512 UTF8 bytes; transport granularity only.
        piece = text[offset:end]
        if end < len(text):
            self.pending.appendleft((text, end))
        return encode_caption(piece)
