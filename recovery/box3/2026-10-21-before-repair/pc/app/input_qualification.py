"""Cheap exclusions only: never infer speech from amplitude or ban short words."""
import unicodedata
import numpy as np

def pcm_has_signal(pcm):
    return bool(pcm) and len(pcm)%2==0 and bool(np.any(np.frombuffer(pcm,dtype='<i2')))

def meaningful_text(text):
    return isinstance(text,str) and any(unicodedata.category(c)[0] in 'LN' for c in text)
