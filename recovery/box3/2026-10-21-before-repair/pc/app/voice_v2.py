"""Opt-in v2 framed transport. Authentication precedes all turn allocation."""
import asyncio
import hashlib
import json
import struct
from fastapi import APIRouter, Request, HTTPException
from starlette.responses import StreamingResponse, JSONResponse
from .device_auth import require_device_token
from .audio_input import bounded_chunks, AudioInputTooLarge, AudioInputIdleTimeout
from .voice_turn import TurnError
from .tx_audio_quantity import stereo_output_bytes


def packet(kind, data):
    return kind + struct.pack('!I',len(data)) + data


async def frames(request, limit):
    buf=bytearray()
    async for chunk in bounded_chunks(request.stream(),limit,idle_timeout_seconds=5):
        # ASGI chunks are not protocol frames; drain before accepting more.
        for offset in range(0,len(chunk),16384):
            buf.extend(chunk[offset:offset+16384])
            while len(buf)>=5:
                kind=bytes(buf[:1]);size=int.from_bytes(buf[1:5],'big')
                if kind not in (b'P',b'E') or size<1 or size>(16384 if kind==b'P' else 512):
                    raise TurnError('invalid_frame',400)
                if len(buf)<5+size: break
                payload=bytes(buf[5:5+size]);del buf[:5+size]
                yield kind,payload
    if buf: raise TurnError('truncated_frame',400)


def integer(request,name):
    values=request.headers.getlist(name)
    if len(values)!=1 or not values[0].isascii() or not values[0].isdigit() or len(values[0])>10:
        raise TurnError('invalid_header',400)
    return int(values[0])


def identity(request):
    values=request.headers.getlist('x-voice-session')
    if len(values)!=1: raise TurnError('invalid_header',400)
    return values[0],integer(request,'x-voice-turn'),integer(request,'x-voice-revision')


def apply_prior_events(request,store,session,number):
    values=request.headers.getlist('x-voice-prior-events')
    if not values:return
    if len(values)!=1 or len(values[0])>1024:raise TurnError('invalid_prior_events',400)
    data=json.loads(values[0])
    if not isinstance(data,dict) or set(data)!={'session','turn','revision','events'}:raise TurnError('invalid_prior_events',400)
    if data['session']!=session or type(data['turn']) is not int or data['turn']!=number-1:raise TurnError('prior_event_owner',400)
    events=data['events']
    if not isinstance(events,list) or not 1<=len(events)<=2:raise TurnError('invalid_prior_events',400)
    for event in events:
        if not isinstance(event,dict) or set(event)-{'seq','kind','frames','completion','tx','generation'}:raise TurnError('invalid_prior_events',400)
        if event.get('kind') not in ('play_started','play_finished','interrupted'):raise TurnError('invalid_prior_events',400)
        store.event(session,data['turn'],data['revision'],event['seq'],event['kind'],event.get('frames',0),event.get('completion'),event.get('tx'),event.get('generation'))


def make_router(resolve):
    router=APIRouter()
    def service(request):
        require_device_token(request)
        # v2 cannot allocate unauthenticated sessions even when v1 observes tokens.
        auth=request.app.state.device_auth
        if auth.mode!='required': raise HTTPException(503,'v2 requires strict authentication')
        value=resolve()
        if value is None: raise HTTPException(503,'v2 disabled')
        return value

    def respond(svc,turn,session,number,revision,seq):
        store=svc.store
        if turn.response_claim_revision == revision:
            return JSONResponse({"status":"duplicate","segment":seq})
        turn.response_claim_revision=revision
        async def body():
            task=asyncio.current_task()
            if len(store.outputs)>=2:
                store.retire(turn,'output_capacity')
                yield packet(b'X',b'{"error":"output_capacity"}')
                return
            store.outputs.add(task)
            turn.candidate=task
            try:
                text=await store.merged(turn,revision,seq)
                if not store.current(turn,revision):return
                meta=json.dumps({'session':session,'turn':number,'revision':revision,'last_segment':seq}).encode()
                yield packet(b'M',meta)
                async for data in svc.answer(text,turn,revision):
                    if not store.current(turn,revision):return
                    turn.expected_tx_bytes+=stereo_output_bytes(data)
                    turn.frame_count+=1
                    yield packet(b'F',struct.pack('!I',turn.frame_count)+data)
                if store.current(turn,revision):
                    turn.generated=True
                    yield packet(b'D',json.dumps({'frames':turn.frame_count}).encode())
            except TurnError as exc:
                if store.current(turn,revision):store.retire(turn,exc.code)
                yield packet(b'X',json.dumps({'error':exc.code}).encode())
            except asyncio.CancelledError:
                raise
            except Exception:
                if store.current(turn,revision):
                    store.retire(turn,'candidate_failed')
                    yield packet(b'X',b'{"error":"candidate_failed"}')
            finally:
                if turn.candidate is task:turn.candidate=None
                store.outputs.discard(task)
        return StreamingResponse(body(),media_type='application/x-voice-v2')

    @router.get('/api/v2/voice/health')
    async def protocol_health(request:Request):
        svc=service(request)
        body=svc.health()
        from .discovery_runtime import runtime
        discovery=runtime(request)
        if discovery is not None:
            discovery.receipts.health(request,body.get('ready') is True)
            body.update(discovery.status())
        return body

    @router.post('/api/v2/voice/stream')
    async def stream(request:Request):
        svc=service(request);store=svc.store;turn=seg=None;duplicate=False
        try:
            session,number,revision=identity(request)
            seq=integer(request,'x-voice-segment');start=integer(request,'x-voice-sample-start')
            turn,seg,duplicate=store.reserve(session,number,seq,revision,start,commit=False)
            digest=hashlib.sha256();count=0;end=None
            async for kind,payload in frames(request,store.limits.segment_bytes+4096):
                if end is not None: raise TurnError('data_after_end',400)
                if kind==b'P':
                    count+=len(payload)
                    if count>store.limits.segment_bytes or len(payload)%2: raise TurnError('pcm_bounds',413)
                    digest.update(payload)
                    if not duplicate:
                        if seg is None:
                            apply_prior_events(request,store,session,number)
                            turn,seg,duplicate=store.reserve(session,number,seq,revision,start)
                            # Another completed request may have won while this
                            # connection was waiting for its first PCM packet.
                        if not duplicate:store.append(turn,seg,payload)
                else:
                    end=json.loads(payload)
                    if not isinstance(end,dict) or set(end)!={'reason','samples','sha256'}:raise TurnError('invalid_end',400)
            if end is None:raise TurnError('missing_end',400)
            if type(end['samples']) is not int or end['samples']*2!=count or end['sha256']!=digest.hexdigest():raise TurnError('segment_digest',400)
            if duplicate:
                if (seg.digest,seg.samples,seg.reason)!=(end['sha256'],end['samples'],end['reason']):raise TurnError('replay_conflict')
                return JSONResponse({'status':'duplicate','segment':seq})
            if seg is None:raise TurnError('no_speech',400)
            store.finish(turn,seg,end['reason'],end['samples'],end['sha256'],svc.recognize)
            if seg.reason=='segment_limit':
                return JSONResponse({'status':'segment_accepted','segment':seq})

            return respond(svc,turn,session,number,revision,seq)
        except TurnError as exc:
            if turn is not None and seg is not None and not duplicate and not seg.complete:store.retire(turn,exc.code)
            raise HTTPException(exc.status,exc.code) from None
        except (AudioInputTooLarge,AudioInputIdleTimeout) as exc:
            if turn is not None and seg is not None and not duplicate:store.retire(turn,'body_limit')
            raise HTTPException(413 if isinstance(exc,AudioInputTooLarge) else 408,'body_limit') from None
        except (ValueError,TypeError,KeyError):
            if turn is not None and seg is not None and not duplicate:store.retire(turn,'invalid_body')
            raise HTTPException(400,'invalid_body') from None
        except BaseException:
            if turn is not None and not duplicate and seg is not None and not seg.complete:store.retire(turn,'upload_disconnected')
            raise

    @router.post('/api/v2/voice/commit')
    async def commit_boundary(request:Request):
        svc=service(request);store=svc.store
        try:
            session,number,revision=identity(request)
            seq=integer(request,'x-voice-segment')
            start=integer(request,'x-voice-sample-start')
            raw=bytearray()
            async for chunk in bounded_chunks(request.stream(),256,idle_timeout_seconds=5):raw.extend(chunk)
            data=json.loads(raw)
            if not isinstance(data,dict) or set(data)!={'samples','sha256'}:raise TurnError('invalid_commit',400)
            turn=store.identify(session,number)
            seg=turn.segments.get(seq)
            if (turn is not store.turn or revision!=turn.revision or seq!=len(turn.segments)-1
                or seg is None or not seg.complete or seg.reason!='segment_limit'
                or seg.start!=start or seg.revision!=revision):raise TurnError('invalid_commit')
            if type(data['samples']) is not int or (data['samples'],data['sha256'])!=(seg.samples,seg.digest):raise TurnError('segment_digest',400)
            return respond(svc,turn,session,number,revision,seq)
        except TurnError as exc:raise HTTPException(exc.status,exc.code) from None
        except (AudioInputTooLarge,AudioInputIdleTimeout):raise HTTPException(413,'commit_body_limit') from None
        except (ValueError,TypeError,KeyError):raise HTTPException(400,'invalid_commit') from None

    @router.post('/api/v2/voice/events')
    async def events(request:Request):
        svc=service(request)
        try:
            session,number,revision=identity(request)
            raw=bytearray()
            async for chunk in bounded_chunks(request.stream(),512,idle_timeout_seconds=5):raw.extend(chunk)
            event=json.loads(raw)
            if not isinstance(event,dict) or set(event)-{'seq','kind','frames','completion','tx','generation'}:raise TurnError('invalid_event',400)
            result=svc.store.event(session,number,revision,event['seq'],event['kind'],event.get('frames',0),event.get('completion'),event.get('tx'),event.get('generation'))
            return {'status':result}
        except TurnError as exc:raise HTTPException(exc.status,exc.code) from None
        except (AudioInputTooLarge,AudioInputIdleTimeout):raise HTTPException(413,'event_body_limit') from None
        except (ValueError,TypeError,KeyError):raise HTTPException(400,'invalid_event') from None

    @router.get('/api/v2/voice/session')
    async def session_challenge(request:Request):
        return {'challenge':service(request).store.session_challenge()}

    @router.post('/api/v2/voice/session')
    async def reset_session(request:Request):
        svc=service(request)
        from .discovery_runtime import runtime
        discovery=runtime(request)
        if discovery is not None and not discovery.receipts.session_allowed(request):raise HTTPException(409,'stale_box_origin')
        try:
            raw=bytearray()
            async for chunk in bounded_chunks(request.stream(),256,idle_timeout_seconds=5):raw.extend(chunk)
            data=json.loads(raw)
            if not isinstance(data,dict) or set(data)!={'session','challenge'}:raise TurnError('invalid_session',400)
            svc.store.reset_session(data['session'],data['challenge'])
            if discovery is not None:discovery.receipts.session(request,svc.store)
            result={'status':'registered'}
            if discovery is not None:result['pc_instance']=discovery.instance.hex()
            return result
        except TurnError as exc:raise HTTPException(exc.status,exc.code) from None
        except (AudioInputTooLarge,AudioInputIdleTimeout):raise HTTPException(413,'session_body_limit') from None
        except (ValueError,TypeError,KeyError):raise HTTPException(400,'invalid_session') from None
    return router
