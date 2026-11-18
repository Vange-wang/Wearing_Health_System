#include "audio_session.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>

static uint32_t finish_capture_and_acquire_talk(void)
{
    assert(audio_session_begin_capture());
    const uint32_t generation = audio_session_capture_generation();
    assert(generation != 0U);
    audio_session_complete_capture(generation);
    assert(audio_session_acquire_playback(AUDIO_SESSION_OWNER_TALK));
    return generation;
}

static void test_current_talk_generation_can_be_cancelled(void)
{
    assert(audio_session_init());
    const uint32_t generation = finish_capture_and_acquire_talk();

    assert(audio_session_cancel_talk(generation));
    assert(audio_session_should_cancel(AUDIO_SESSION_OWNER_TALK));
}

static void test_stale_generation_cannot_cancel_current_talk(void)
{
    assert(audio_session_init());
    const uint32_t stale_generation = finish_capture_and_acquire_talk();
    audio_session_release(AUDIO_SESSION_OWNER_TALK);

    const uint32_t current_generation = finish_capture_and_acquire_talk();
    assert(current_generation != stale_generation);
    assert(!audio_session_cancel_talk(stale_generation));
    assert(!audio_session_should_cancel(AUDIO_SESSION_OWNER_TALK));
    assert(audio_session_owner_is(AUDIO_SESSION_OWNER_TALK));
}

static void test_release_clears_talk_cancel(void)
{
    assert(audio_session_init());
    const uint32_t generation = finish_capture_and_acquire_talk();
    assert(audio_session_cancel_talk(generation));

    audio_session_release(AUDIO_SESSION_OWNER_TALK);
    assert(!audio_session_should_cancel(AUDIO_SESSION_OWNER_TALK));
    assert(!audio_session_owner_is(AUDIO_SESSION_OWNER_TALK));
}

static void test_non_talk_owner_is_protected(void)
{
    assert(audio_session_init());
    assert(audio_session_begin_capture());
    const uint32_t generation = audio_session_capture_generation();
    audio_session_complete_capture(generation);

    assert(!audio_session_cancel_talk(generation));
    assert(!audio_session_should_cancel(AUDIO_SESSION_OWNER_TALK));

    assert(audio_session_acquire_playback(AUDIO_SESSION_OWNER_ALERT));
    assert(!audio_session_cancel_talk(generation));
    assert(audio_session_owner_is(AUDIO_SESSION_OWNER_ALERT));
    assert(!audio_session_should_cancel(AUDIO_SESSION_OWNER_TALK));
}

int main(void)
{
    test_current_talk_generation_can_be_cancelled();
    test_stale_generation_cannot_cancel_current_talk();
    test_release_clears_talk_cancel();
    test_non_talk_owner_is_protected();
    puts("audio_session_new_host_test: PASS");
    return 0;
}
