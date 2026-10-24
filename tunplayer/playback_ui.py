"""Player display choices and a deterministic five-second inactivity policy."""
import time


def browser_layout(width,preferred=310):
    """Keep 640 px for video; a narrow window initially folds the browser."""
    return width<1120,max(240,min(460,int(preferred),max(240,width-646)))


def offers_resume(channel):
    return (channel.get('kind') in ('movie','episode','series') and not channel.get('demo')
            and not channel.get('completed') and float(channel.get('position') or 0)>=10)


def escape_action(settings_open,browser_visible,fullscreen):
    if settings_open:return 'settings'
    if browser_visible:return 'browser'
    if fullscreen:return 'fullscreen'
    return None

ASPECT_MODES={
    'auto':('Auto','-1','yes','0'),
    '16:9':('16:9','16:9','yes','0'),
    '4:3':('4:3','4:3','yes','0'),
    '21:9':('21:9','21:9','yes','0'),
    '1:1':('Carré','1:1','yes','0'),
    'fill':('Remplir','-1','yes','1'),
    'stretch':('Étirer','-1','no','0'),
}

class PlaybackIdle:
    def __init__(self,timeout=5.0,clock=time.monotonic):
        self.timeout=timeout;self.clock=clock;self.active=False;self.hidden=False;self.last_activity=clock()

    def activity(self):
        self.last_activity=self.clock();self.hidden=False

    def reset(self):
        self.active=False;self.activity()

    def update(self,active,held=False):
        if not active:
            self.reset();return False
        if not self.active:
            self.active=True;self.activity()
        if held:self.activity()
        self.hidden=self.clock()-self.last_activity>=self.timeout
        return self.hidden
