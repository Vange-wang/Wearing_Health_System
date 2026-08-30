#include <assert.h>
#include <stdint.h>
#include <stdio.h>

#include "audio_session.h"

static void test_short_press_discards_capture(void)
{
    int16_t captured[] = { 11, 12, 13, 14 };
    int16_t output[8] = { 0 };

    audio_session_init();
    assert(audio_session_begin_capture());
    assert(audio_session_write_capture(captured, 4) == 4);
    assert(audio_session_cancel_short_press());
    assert(!audio_session_confirm_long_press());
    assert(audio_session_read_capture(output, 8) == 0);
}

static void test_long_press_drains_prebuffer_once_before_live(void)
{
    int16_t prebuffer[] = { 1, 2, 3 };
    int16_t live[] = { 4, 5 };
    int16_t output[8] = { 0 };

    audio_session_init();
    assert(audio_session_begin_capture());
    assert(audio_session_write_capture(prebuffer, 3) == 3);
    assert(audio_session_confirm_long_press());
    assert(audio_session_write_capture(live, 2) == 2);
    assert(audio_session_read_capture(output, 8) == 5);
    for (size_t i = 0; i < 5; ++i) {
        assert(output[i] == (int16_t)(i + 1));
    }
    assert(audio_session_read_capture(output, 8) == 0);
}

static void test_talk_cancels_alert_lease(void)
{
    audio_session_init();
    assert(audio_session_acquire_playback(AUDIO_SESSION_OWNER_ALERT));
    assert(audio_session_begin_capture());
    assert(audio_session_should_cancel(AUDIO_SESSION_OWNER_ALERT));
    assert(!audio_session_owner_is(AUDIO_SESSION_OWNER_ALERT));
    assert(audio_session_acquire_playback(AUDIO_SESSION_OWNER_TALK));
}

static void test_two_playback_owners_cannot_coexist(void)
{
    audio_session_init();
    assert(audio_session_acquire_playback(AUDIO_SESSION_OWNER_ALERT));
    assert(!audio_session_acquire_playback(AUDIO_SESSION_OWNER_TALK));
    audio_session_release(AUDIO_SESSION_OWNER_ALERT);
    assert(audio_session_acquire_playback(AUDIO_SESSION_OWNER_TALK));
}

int main(void)
{
    test_short_press_discards_capture();
    test_long_press_drains_prebuffer_once_before_live();
    test_talk_cancels_alert_lease();
    test_two_playback_owners_cannot_coexist();
    puts("audio_session_host_test: PASS");
    return 0;
}
