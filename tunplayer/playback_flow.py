"""Bounded reconnects and cancellable next-episode countdowns, independent of GTK."""
import math
import time
from urllib.parse import urlsplit


def remote_stream(url):
    return urlsplit(url).scheme.lower() in ('http','https','rtsp','rtmp','udp','rtp')

class ReconnectPolicy:
    def __init__(self,delays=(1,2,4,8),clock=time.monotonic):
        self.delays=delays;self.clock=clock;self.reset()

    def reset(self):
        self.attempts=0;self.deadline=None;self.inflight=False;self.cancelled=False;self.healthy_since=None

    @property
    def pending(self):return self.deadline is not None

    def failure(self):
        self.healthy_since=None;self.inflight=False
        if self.cancelled:return False
        if self.pending:return True
        if self.attempts>=len(self.delays):return False
        delay=self.delays[self.attempts];self.attempts+=1;self.deadline=self.clock()+delay
        return True

    def take_due(self):
        if not self.pending or self.clock()<self.deadline:return False
        self.deadline=None;self.inflight=True;return True

    def loaded(self):
        self.deadline=None;self.inflight=False;self.healthy_since=self.clock()

    def healthy(self,advancing=True):
        if not advancing:self.healthy_since=None;return
        if self.healthy_since is None:self.healthy_since=self.clock()
        if self.clock()-self.healthy_since>=10:self.attempts=0

    def cancel(self):
        self.cancelled=True;self.deadline=None;self.inflight=False;self.healthy_since=None

    def remaining(self):
        return max(0,math.ceil(self.deadline-self.clock())) if self.pending else 0

class NextEpisodeCountdown:
    def __init__(self,delay=5,clock=time.monotonic):
        self.delay=delay;self.clock=clock;self.cancel()

    @property
    def pending(self):return self.target is not None

    def schedule(self,target):
        self.target=target;self.deadline=self.clock()+self.delay

    def remaining(self):
        return max(0,math.ceil(self.deadline-self.clock())) if self.pending else 0

    def take_due(self,immediately=False):
        if not self.pending or (not immediately and self.clock()<self.deadline):return None
        target=self.target;self.cancel();return target

    def cancel(self):self.target=None;self.deadline=None
