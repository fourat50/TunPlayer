import unittest
from tunplayer.playback_ui import PlaybackIdle,browser_layout,offers_resume,escape_action


class PlayerPolicies(unittest.TestCase):
    def test_browser_folds_in_small_window_and_preserves_video_minimum(self):
        self.assertEqual(browser_layout(1380,420),(False,420))
        self.assertEqual(browser_layout(1080,460),(True,434))
        self.assertEqual(browser_layout(900,460),(True,254))
        self.assertEqual(browser_layout(1380,900),(False,460))
        self.assertEqual(browser_layout(1380,100),(False,240))

    def test_resume_is_offered_only_for_started_unfinished_vod(self):
        for kind in ('movie','episode','series'):
            self.assertTrue(offers_resume(dict(kind=kind,position=10)))
            self.assertFalse(offers_resume(dict(kind=kind,position=9.99)))
            self.assertFalse(offers_resume(dict(kind=kind,position=300,completed=True)))
        self.assertFalse(offers_resume(dict(kind='live',position=300)))
        self.assertFalse(offers_resume(dict(kind='movie',position=300,demo=True)))

    def test_escape_closes_layers_in_order_without_stopping_media(self):
        self.assertEqual(escape_action(True,True,True),'settings')
        self.assertEqual(escape_action(False,True,True),'browser')
        self.assertEqual(escape_action(False,False,True),'fullscreen')
        self.assertIsNone(escape_action(False,False,False))

class Inactivity(unittest.TestCase):
    def setUp(self):
        self.now=0.0;self.idle=PlaybackIdle(clock=lambda:self.now)

    def test_hides_at_five_seconds_and_not_before(self):
        self.assertFalse(self.idle.update(True))
        self.now=4.999;self.assertFalse(self.idle.update(True))
        self.now=5;self.assertTrue(self.idle.update(True))

    def test_input_restores_controls_and_restarts_the_countdown(self):
        self.idle.update(True);self.now=8;self.assertTrue(self.idle.update(True))
        self.idle.activity();self.assertFalse(self.idle.hidden)
        self.now=12.9;self.assertFalse(self.idle.update(True))
        self.now=13;self.assertTrue(self.idle.update(True))

    def test_dragging_or_open_menu_keeps_controls_visible(self):
        self.idle.update(True);self.now=20;self.assertFalse(self.idle.update(True,held=True))
        self.now=24.9;self.assertFalse(self.idle.update(True))
        self.now=25;self.assertTrue(self.idle.update(True))

    def test_leaving_player_or_failed_load_restores_controls(self):
        self.idle.update(True);self.now=6;self.assertTrue(self.idle.update(True))
        self.assertFalse(self.idle.update(False));self.assertFalse(self.idle.hidden)
        self.now=100;self.assertFalse(self.idle.update(True))
        self.now=104.9;self.assertFalse(self.idle.update(True))
        self.now=105;self.assertTrue(self.idle.update(True))

if __name__=='__main__':unittest.main()
