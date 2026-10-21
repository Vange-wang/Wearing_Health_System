"""In-memory, one authenticated device turn. No supplier/tool execution here."""
import asyncio
from dataclasses import dataclass, field
import hashlib
import re
import time
import secrets
from .input_qualification import meaningful_text
from .asr import ASRError
from .tx_completion import canonical_evidence


class TurnError(Exception):
    def __init__(self, code, status=409):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class Limits:
    seconds: int = 120
    segments: int = 16
    chars: int = 8000
    pending: int = 2
    ttl: int = 120
    segment_bytes: int = 480000
    def __post_init__(self):
        if any(type(x) is not int for x in (self.seconds,self.segments,self.chars,self.pending,self.ttl,self.segment_bytes)):
            raise ValueError('v2 limits must be integers')
        if not (15 <= self.seconds <= 120 and 1 <= self.segments <= 16
                and 1 <= self.chars <= 8000 and 1 <= self.pending <= 2
                and 1 <= self.ttl <= 120 and 2 <= self.segment_bytes <= 480000):
            raise ValueError('v2 limits out of bounds')


@dataclass
class Segment:
    seq: int
    start: int
    revision: int
    pcm: bytearray = field(default_factory=bytearray)
    digest: str = ''
    reason: str = ''
    samples: int = 0
    text: str = ''
    task: object = None
    complete: bool = False


@dataclass
class Turn:
    session: str
    number: int
    revision: int = 1
    segments: dict = field(default_factory=dict)
    bytes_received: int = 0
    active: bool = True
    candidate: object = None
    played: bool = False
    delivered: bool = False
    generated: bool = False
    frame_count: int = 0
    expected_tx_bytes: int = 0
    output_generation: int = 0
    response_claim_revision: int = 0
    draft: tuple = None
    event_seq: int = 0
    last_event: tuple = None
    timer: object = None
    failure: str = ''
    events: dict = field(default_factory=dict)
    user_saved: bool = False
    retired_at: float = 0.0


class TurnStore:
    def __init__(self, history, limits=Limits()):
        self.history, self.limits = history, limits
        self.turn = None
        self.session = None
        self.last_turn = 0
        self.cleanup = set()
        self.retired = {}
        self.outputs=set()
        self.output_leases={}
        self.sessions_seen=set()
        self.challenge=None

    def session_challenge(self):
        self.challenge=(secrets.token_hex(16),time.monotonic()+30)
        return self.challenge[0]

    def reset_session(self,session,nonce):
        if not re.fullmatch('[a-f0-9]{32}',session or '') or not isinstance(nonce,str):raise TurnError('invalid_session',400)
        if self.challenge is None or time.monotonic()>self.challenge[1] or not secrets.compare_digest(nonce,self.challenge[0]):
            raise TurnError('invalid_session_challenge')
        self.challenge=None
        if session in self.sessions_seen:raise TurnError('session_replay')
        if len(self.sessions_seen)>=64:raise TurnError('session_capacity',413)
        if self.turn:self.retire(self.turn,'session_reset')
        self.sessions_seen.add(session)
        self.session=session;self.last_turn=0;self.turn=None
        for old in list(self.retired.values()):self.forget(old)
        self.history.clear()

    def touch(self, turn):
        if turn.timer: turn.timer.cancel()
        turn.timer = asyncio.get_running_loop().call_later(
            self.limits.ttl, self.retire, turn, 'expired')

    def retire(self, turn, reason='cancelled', *, cancel_candidate=True):
        if not turn.active: return
        turn.active = False
        turn.retired_at = time.monotonic()
        turn.failure = reason
        if turn.timer: turn.timer.cancel()
        if cancel_candidate and turn.candidate and turn.candidate is not asyncio.current_task(): turn.candidate.cancel()
        for seg in turn.segments.values():
            if seg.task and not seg.task.done() and seg.task is not asyncio.current_task(): seg.task.cancel()
            # Running ASR owns its PCM until its finally executes.
            if seg.task is None or seg.task.done():
                seg.pcm[:] = b'\0' * len(seg.pcm)
                seg.pcm.clear()
        turn.draft = None
        self.retired[(turn.session,turn.number)] = turn
        while len(self.retired)>4:
            old=self.retired.pop(next(iter(self.retired)))
            self.forget(old)
        turn.timer=asyncio.get_running_loop().call_later(self.limits.ttl,self.forget,turn)

    def forget(self,turn):
        if turn.timer:turn.timer.cancel()
        for seg in turn.segments.values():seg.text=''
        turn.events.clear();turn.draft=None
        self.retired.pop((turn.session,turn.number),None)

    def save_input(self,turn):
        if not turn.user_saved:
            texts=[s.text for s in turn.segments.values()]
            if texts and all(texts):
                self.history.remember_input('\n'.join(texts))
                turn.user_saved=True

    def identify(self, session, number):
        if not re.fullmatch('[a-f0-9]{32}', session or '') or type(number) is not int or not 1 <= number <= 0xffffffff:
            raise TurnError('invalid_identity', 400)
        # Session is bound to this authenticated device process lifetime.
        # Changing boot/session requires explicit reset while no active turn.
        if self.session is None:raise TurnError('session_registration_required')
        if session != self.session:
            raise TurnError('session_mismatch')
        if self.turn and self.turn.number == number:
            if not self.turn.active: raise TurnError(self.turn.failure or 'retired')
            return self.turn
        if number != self.last_turn + 1: raise TurnError('turn_sequence')
        # A provisional identity has no side effects. reserve validates the
        # complete header contract before committing ownership below.
        return Turn(session, number)

    def advance(self, turn, revision):
        if not turn.active: raise TurnError('retired')
        if type(revision) is not int or not 1 <= revision <= self.limits.segments:
            raise TurnError('invalid_revision', 400)
        if revision < turn.revision: raise TurnError('stale_revision')
        if revision > turn.revision:
            if revision != turn.revision + 1 or turn.played: raise TurnError('revision_sequence')
            if turn.candidate: turn.candidate.cancel()
            turn.revision = revision
            turn.candidate = None
            turn.draft = None
            turn.generated = False
            turn.frame_count = 0
            turn.expected_tx_bytes = 0
            turn.output_generation = 0
        self.touch(turn)

    def reserve(self, session, number, seq, revision, start, *, commit=True):
        turn = self.identify(session, number)
        new_turn = turn is not self.turn
        if any(type(x) is not int for x in (seq, revision, start)) or not 0 <= seq < self.limits.segments or start < 0:
            raise TurnError('invalid_segment', 400)
        if revision != seq + 1: raise TurnError('segment_revision', 400)
        if seq in turn.segments:
            seg = turn.segments[seq]
            if seg.start != start or seg.revision != revision: raise TurnError('segment_conflict')
            if not seg.complete: raise TurnError('segment_inflight')
            return turn, seg, True
        if seq != len(turn.segments): raise TurnError('segment_gap')
        if turn.played: raise TurnError('already_playing')
        if seq and (not turn.segments[seq-1].complete or start != turn.segments[seq-1].start + turn.segments[seq-1].samples):
            raise TurnError('sample_sequence')
        if not seq and start != 0: raise TurnError('sample_sequence')
        if revision < turn.revision: raise TurnError('stale_revision')
        if revision > turn.revision and revision != turn.revision + 1:
            raise TurnError('revision_sequence')
        pending = len(self.cleanup) + sum(not s.complete for s in turn.segments.values())
        if pending >= self.limits.pending:
            if commit and not new_turn:self.retire(turn, 'input_capacity')
            raise TurnError('input_capacity', 413)
        if not commit:return turn, None, False
        if new_turn:
            # All header checks succeeded; no await splits the ownership swap.
            if self.turn and self.turn.active:
                self.save_input(self.turn)
                self.retire(self.turn, 'superseded')
            self.session, self.last_turn, self.turn = session, number, turn
        self.advance(turn, revision)
        seg = Segment(seq, start, revision)
        turn.segments[seq] = seg
        return turn, seg, False

    def append(self, turn, seg, pcm):
        if not turn.active: raise TurnError('retired')
        if not pcm or len(pcm) % 2: raise TurnError('pcm_alignment', 400)
        if len(seg.pcm) + len(pcm) > self.limits.segment_bytes or turn.bytes_received + len(pcm) > self.limits.seconds * 32000:
            self.retire(turn, 'input_capacity')
            raise TurnError('input_capacity', 413)
        seg.pcm.extend(pcm)
        turn.bytes_received += len(pcm)
        self.touch(turn)

    def finish(self, turn, seg, reason, samples, digest, asr):
        if reason not in ('soft_endpoint','segment_limit','explicit_end') or type(samples) is not int or not isinstance(digest, str):
            raise TurnError('invalid_end', 400)
        if not seg.pcm or samples * 2 != len(seg.pcm) or hashlib.sha256(seg.pcm).hexdigest() != digest:
            raise TurnError('segment_digest', 400)
        if reason == 'segment_limit' and len(seg.pcm) != self.limits.segment_bytes:
            raise TurnError('invalid_split', 400)
        seg.samples, seg.digest, seg.reason, seg.complete = samples, digest, reason, True
        async def recognize():
            try:
                result = await asr(seg.pcm)
                if not turn.active: raise TurnError('retired')
                if not meaningful_text(result): raise TurnError('no_speech',400)
                if len(result) + sum(len(s.text) for s in turn.segments.values()) > self.limits.chars:
                    raise TurnError('text_capacity',413)
                seg.text = result.strip()
                return seg.text
            except asyncio.CancelledError: raise
            except Exception as exc:
                no_speech = (isinstance(exc, TurnError) and exc.code == 'no_speech') or (
                    isinstance(exc, ASRError) and exc.args in [('no_signal',), ('no_meaningful_speech',)])
                code = 'no_speech' if no_speech else 'recognition_failed'
                # Retire input/resources without cancelling the HTTP body that
                # must still send its explicit X terminal to the client.
                self.retire(turn, code, cancel_candidate=False)
                raise TurnError(code, 400 if no_speech else 502) from None
            finally:
                seg.pcm[:] = b'\0' * len(seg.pcm)
                seg.pcm.clear()
        seg.task = asyncio.create_task(recognize())
        self.cleanup.add(seg.task)
        def done(task):
            self.cleanup.discard(task)
            # A task cancelled before its first step never enters recognize's
            # finally; completion is the safe fallback owner of this buffer.
            seg.pcm[:] = b'\0' * len(seg.pcm)
            seg.pcm.clear()
            if not task.cancelled(): task.exception()
        seg.task.add_done_callback(done)

    def current(self, turn, revision):
        return self.turn is turn and turn.active and turn.revision == revision

    async def merged(self, turn, revision, seq):
        for index in range(seq+1):
            seg = turn.segments[index]
            if not seg.complete or seg.task is None: raise TurnError('incomplete_input')
            try:
                await asyncio.shield(seg.task)  # response cancellation must preserve earlier ASR
            except asyncio.CancelledError:
                # Another segment's ASR failure can cancel this awaited segment.
                # Preserve real response cancellation/disconnect semantics.
                task = asyncio.current_task()
                if not task.cancelling() and not turn.active and turn.failure in ('no_speech', 'recognition_failed'):
                    raise TurnError(turn.failure, 400 if turn.failure == 'no_speech' else 502) from None
                raise
            if not self.current(turn, revision): raise TurnError('stale_revision')
        return '\n'.join(turn.segments[i].text for i in range(seq+1))

    def event(self, session, number, revision, event_seq, kind, frames=0, completion=None, tx=None, generation=None):
        turn = self.turn
        if turn is None or turn.session != session or turn.number != number:
            turn=self.retired.get((session,number))
        if turn is None: raise TurnError('event_owner')
        if not turn.active and time.monotonic()-turn.retired_at>self.limits.ttl:raise TurnError('expired')
        proof = None
        if kind == 'play_finished':
            if completion != 'tx_dma_completed':raise TurnError('incomplete_delivery')
            try:proof = canonical_evidence(tx)
            except ValueError:raise TurnError('invalid_tx_evidence',400) from None
        elif tx is not None:raise TurnError('invalid_tx_evidence',400)
        if kind=='play_started' and (type(generation) is not int or not 0<generation<=0xffffffff):raise TurnError('invalid_generation',400)
        event = (revision,event_seq,kind,frames,completion,proof,generation)
        if type(event_seq) is not int or event_seq<1 or event_seq>256:raise TurnError('event_sequence',400)
        if event_seq in turn.events:
            if turn.events[event_seq]!=event:raise TurnError('event_conflict')
            return 'duplicate'
        if len(turn.events)>=64:raise TurnError('event_capacity',413)
        if not turn.active:
            if turn.failure=='superseded' and kind in ('play_started','interrupted') and revision==turn.revision:
                self.save_input(turn)
                turn.events[event_seq]=event
                return 'retired_receipt'
            raise TurnError('retired')
        if kind == 'continuation': self.advance(turn,revision)
        elif not self.current(turn,revision): raise TurnError('stale_revision')
        elif kind == 'play_started':
            if turn.frame_count < 1: raise TurnError('no_audio')
            if turn.output_generation and turn.output_generation!=generation:raise TurnError('generation_conflict')
            turn.output_generation = generation
            turn.played = True
        elif kind == 'play_finished':
            if not turn.played or not turn.generated or turn.draft is None or type(frames) is not int or frames != turn.frame_count:
                raise TurnError('incomplete_delivery')
            if (tx['session'],tx['turn'],tx['revision'],tx['generation'])!=(session,number,revision,turn.output_generation):raise TurnError('tx_owner')
            if turn.expected_tx_bytes<=0 or tx['accepted_bytes']!=turn.expected_tx_bytes:raise TurnError('tx_quantity')
            self.history.remember(*turn.draft)
            turn.delivered = True
            self.retire(turn,'delivered')
        elif kind in ('interrupted','turn_cancel'):
            if turn.played:self.save_input(turn)
            self.retire(turn,'partial_cancelled' if turn.played else 'cancelled')
        else: raise TurnError('invalid_event',400)
        turn.event_seq, turn.last_event = max(event_seq,turn.event_seq),event
        turn.events[event_seq]=event
        return 'accepted'

    async def close(self):
        if self.turn: self.retire(self.turn)
        for task in list(self.outputs):task.cancel()
        if self.outputs:await asyncio.gather(*self.outputs,return_exceptions=True)
        if self.cleanup: await asyncio.gather(*self.cleanup,return_exceptions=True)
        for turn in list(self.retired.values()):self.forget(turn)
