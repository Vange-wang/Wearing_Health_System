"""Match BOX wav_stream's PCM16 mono 16k -> stereo output contract."""
import struct
from .voice_turn import TurnError

def stereo_output_bytes(frame):
    if len(frame)<4:raise TurnError('invalid_output_frame')
    n=int.from_bytes(frame[:4],'big')
    if n==0xffffffff:
        if len(frame)<12 or int.from_bytes(frame[4:12],'big')!=len(frame)-12:
            raise TurnError('invalid_caption_frame')
        return 0
    if n!=len(frame)-4 or n<44:raise TurnError('invalid_output_frame')
    # Only inspect the fixed header; no PCM copy, scan, or buffering.
    h=memoryview(frame)[4:48]
    if bytes(h[:4])!=b'RIFF' or bytes(h[8:16])!=b'WAVEfmt ' or bytes(h[36:40])!=b'data':
        raise TurnError('invalid_output_wav')
    size,fmt_size=struct.unpack_from('<I',h,4)[0],struct.unpack_from('<I',h,16)[0]
    fmt,channels,rate,byte_rate,align,bits=struct.unpack_from('<HHIIHH',h,20)
    pcm=struct.unpack_from('<I',h,40)[0]
    if (size,fmt_size,fmt,channels,rate,byte_rate,align,bits)!=(n-8,16,1,1,16000,32000,2,16) or pcm!=n-44 or pcm%2:
        raise TurnError('unsupported_output_wav')
    return pcm*2
