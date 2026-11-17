import asyncio
import json

import pytest
from starlette.requests import Request

from app.voice_turn import TurnStore, TurnError
from app.voice_v2 import apply_prior_events
from app.voice_v2_service import TurnHistory


def test_first_upload_after_idle_accepts_only_the_identical_delivery_proof():
    async def run():
        session = "1" * 32
        store = TurnStore(TurnHistory())
        store.reset_session(session, store.session_challenge())
        turn, _, _ = store.reserve(session, 1, 0, 1, 0)
        turn.frame_count = 1
        turn.expected_tx_bytes = 4
        turn.generated = True
        turn.draft = ("问题", "回答")
        proof = dict(epoch=1, accepted_bytes=4, completed_bytes=4, write_count=1,
                     fence_seq=1, complete_seq=7, descriptor_count=6, descriptor_mask=63,
                     unknown_partial=False, events_lost=0, cancelled=False,
                     session=session, turn=1, revision=1, generation=1)
        store.event(session, 1, 1, 1, "play_started", generation=1)
        store.event(session, 1, 1, 2, "play_finished", 1, "tx_dma_completed", proof)
        turn.retired_at -= store.limits.ttl + 1
        store.forget(turn)
        events = [dict(seq=1, kind="play_started", generation=1),
                  dict(seq=2, kind="play_finished", frames=1, completion="tx_dma_completed", tx=proof)]
        def replay():
            header = json.dumps(dict(session=session, turn=1, revision=1, events=events)).encode()
            apply_prior_events(Request({"type":"http","headers":[(b"x-voice-prior-events", header)]}),
                               store, session, 2)
        replay()
        events[0]["generation"] = 2
        with pytest.raises(TurnError, match="event_conflict"):
            replay()
        with pytest.raises(TurnError, match="expired"):
            store.event(session, 1, 1, 1, "play_started", generation=1)
        assert store.reserve(session, 2, 0, 1, 0)[0].number == 2
        assert len(store.history.snapshot()) == 2
        await store.close()
    asyncio.run(run())
