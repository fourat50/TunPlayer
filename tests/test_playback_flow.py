import unittest
from tunplayer.playback_flow import ReconnectPolicy,NextEpisodeCountdown,remote_stream

class PlaybackFlow(unittest.TestCase):
    def setUp(self):self.now=0.;self.retry=ReconnectPolicy(clock=lambda:self.now)
    def test_retries_are_spaced_bounded_and_duplicate_errors_do_not_increment(self):
        for index,delay in enumerate((1,2,4,8),1):
            start=self.now;self.assertTrue(self.retry.failure());self.assertEqual(self.retry.attempts,index)
            self.assertTrue(self.retry.failure());self.assertEqual(self.retry.attempts,index)
            self.now=start+delay-.01;self.assertFalse(self.retry.take_due())
            self.now=start+delay;self.assertTrue(self.retry.take_due())
        self.assertFalse(self.retry.failure());self.assertEqual(self.retry.attempts,4)
    def test_successful_open_does_not_reset_budget_until_stable_playback(self):
        self.retry.failure();self.now=1;self.retry.take_due();self.retry.loaded()
        self.assertEqual(self.retry.attempts,1)
        self.now=5;self.retry.healthy();self.assertEqual(self.retry.attempts,1)
        self.now=11;self.retry.healthy();self.assertEqual(self.retry.attempts,0)
    def test_cancel_prevents_late_retry(self):
        self.retry.failure();self.retry.cancel();self.now=100
        self.assertFalse(self.retry.take_due());self.assertFalse(self.retry.failure())
    def test_local_files_are_not_reconnected(self):
        for url in ['/tmp/movie.mp4','file:///tmp/movie.mp4','xtream-series:7']:
            self.assertFalse(remote_stream(url))
        self.assertTrue(remote_stream('https://example.org/live.m3u8'))
    def test_next_episode_is_cancellable_and_emitted_once(self):
        countdown=NextEpisodeCountdown(clock=lambda:self.now);target={'id':'next'}
        countdown.schedule(target);self.now=4.99;self.assertIsNone(countdown.take_due())
        self.now=5;self.assertEqual(countdown.take_due(),target);self.assertIsNone(countdown.take_due())
        countdown.schedule(target);countdown.cancel();self.now=100;self.assertIsNone(countdown.take_due())
    def test_next_episode_can_be_started_immediately(self):
        countdown=NextEpisodeCountdown(clock=lambda:self.now);countdown.schedule({'id':'next'})
        self.assertEqual(countdown.take_due(immediately=True),{'id':'next'})

if __name__=='__main__':unittest.main()
