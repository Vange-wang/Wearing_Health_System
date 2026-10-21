"""One startup numeric event added to the existing passive capture classifier."""
import re


def install(capture_module):
    previous = capture_module.classify_detailed
    pattern = re.compile(
        r'[IWEVD]\s*\((\d{1,10})\)\s+wake_engine:\s*'
        r'wake:threshold word=(\d+) before_milli=(-?\d+) '
        r'requested_milli=(\d+) set=(-?\d+) after_milli=(-?\d+)'
    )

    def classify(line):
        text = capture_module.old.core.ANSI.sub('', line).strip()
        match = pattern.fullmatch(text)
        if match:
            values = list(map(int, match.groups()))
            keys = ('word', 'before_milli', 'requested_milli', 'set', 'after_milli')
            return {'device_ms': values[0], 'tag': 'wake_engine',
                    'kind': 'wake_threshold', 'fields': dict(zip(keys, values[1:]))}, None
        return previous(line)

    capture_module.classify_detailed = classify
