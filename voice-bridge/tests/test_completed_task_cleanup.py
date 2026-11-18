"""Cleanup must harvest failed tasks, including those already done at cancellation."""
import asyncio
import gc
import pytest
from app.stream_resources import RequestResources


@pytest.mark.parametrize('include_running',[False,True])
def test_cleanup_harvests_already_failed_task_without_unretrieved_exception(include_running):
    async def exercise():
        loop=asyncio.get_running_loop();errors=[];closed=[]
        old=loop.get_exception_handler()
        loop.set_exception_handler(lambda loop,context:errors.append(context.get('message')))
        async def failed(): raise RuntimeError('synthetic task failure')
        async def running():
            try: await asyncio.Event().wait()
            finally: closed.append(True)
        try:
            resources=RequestResources()
            resources.task(failed())
            if include_running: resources.task(running())
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            await resources.aclose()
            done=asyncio.Event();resources.when_quiescent(done.set)
            await asyncio.wait_for(done.wait(),1)
            assert closed==([True] if include_running else [])
            del resources
            gc.collect()
            await asyncio.sleep(0)
            gc.collect()
            assert errors==[]
        finally: loop.set_exception_handler(old)
    asyncio.run(exercise())


def test_running_task_cleanup_failure_is_harvested_and_quiescent():
    async def exercise():
        resources=RequestResources()
        async def running():
            try: await asyncio.Event().wait()
            finally: raise RuntimeError('synthetic cancellation cleanup failure')
        task=resources.task(running())
        await asyncio.sleep(0)
        await resources.aclose()
        assert task.done()
        with pytest.raises(RuntimeError,match='synthetic cancellation cleanup failure'):
            await task
        done=asyncio.Event();resources.when_quiescent(done.set)
        await asyncio.wait_for(done.wait(),1)
    asyncio.run(exercise())


def test_harvesting_preserves_failure_for_the_original_consumer():
    async def exercise():
        resources=RequestResources()
        async def failed(): raise RuntimeError('original consumer failure')
        task=resources.task(failed())
        await asyncio.sleep(0)
        await resources.aclose()
        with pytest.raises(RuntimeError,match='original consumer failure'):
            await task
    asyncio.run(exercise())
