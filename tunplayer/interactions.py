"""Clear close actions, visible volume and video-native input dispatch."""
import math
import time
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,Gdk
from .playback_ui import escape_action


class InteractionMixin:
    def init_interactions(self):
        self.muted=self.library.setting('mute','0')=='1';self.last_audible_volume=self.volume or .75
        self.volume_updating=False;self.last_video_double_click=-1.

    def set_volume(self,value):
        try:value=float(value)
        except (ValueError,TypeError):return
        if not math.isfinite(value):return
        self.volume=max(0.,min(1.,value));self.muted=self.volume==0
        if self.volume>0:self.last_audible_volume=self.volume
        self.apply_volume();self.player_activity()

    def apply_volume(self):
        self.persist_setting('volume',self.volume);self.persist_setting('mute','1' if self.muted else '0')
        if self.player:
            try:self.player.set('volume',round(self.volume*100));self.player.set('mute','yes' if self.muted else 'no')
            except RuntimeError:pass
        self.update_volume_controls()

    def update_volume_controls(self):
        if not hasattr(self,'volume_slider'):return
        from .visuals import icon
        self.volume_updating=True
        try:
            self.volume_slider.set_value(round(self.volume*100));self.volume_value.set_text(f'{round(self.volume*100)} %')
            self.mute_image.set_from_pixbuf(icon('mute' if self.muted or self.volume==0 else 'audio',19,'#e4e7ed').get_pixbuf())
            self.mute_button.set_tooltip_text('Réactiver le son · M' if self.muted else 'Couper le son · M')
            self.mute_button.get_accessible().set_name('Réactiver le son' if self.muted else 'Couper le son')
        finally:self.volume_updating=False

    def volume_slider_changed(self,slider):
        if not self.volume_updating:self.set_volume(slider.get_value()/100)

    def toggle_mute(self):
        if self.muted or self.volume==0:
            if self.volume==0:self.volume=self.last_audible_volume or .75
            self.muted=False
        else:self.muted=True
        self.apply_volume();self.player_activity()

    def step_volume(self,direction):self.set_volume(round(self.volume+direction*.05,4))

    def volume_scroll(self,widget,event):
        if event.direction==Gdk.ScrollDirection.UP:self.step_volume(1)
        elif event.direction==Gdk.ScrollDirection.DOWN:self.step_volume(-1)
        elif event.direction==Gdk.ScrollDirection.SMOOTH:
            values=event.get_scroll_deltas();delta=values[-1]
            if abs(delta)>.01:self.step_volume(-1 if delta>0 else 1)
        self.player_activity();return True

    def video_button(self,widget,event):
        self.player_activity()
        if event.button==1 and event.type==Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self.video_double_click();return True
        return False

    def video_double_click(self):
        now=time.monotonic()
        if self.view=='player' and now-self.last_video_double_click>.35:
            self.last_video_double_click=now;self.toggle_fullscreen()

    def player_escape(self):
        settings=hasattr(self,'player_settings') and self.player_settings.get_visible()
        action=escape_action(settings,self.player_browser_visible(),self.fullscreen)
        if action=='settings':self.player_settings.popdown()
        elif action=='browser':self.toggle_player_browser()
        elif action=='fullscreen':self.toggle_fullscreen()
        elif self.view=='player':self.back_from_playback()

    def player_input(self,action):
        if self.view!='player' or self.closing:return
        self.player_activity()
        if Gtk.grab_get_current() is not None:return
        actions={'fullscreen-double':self.video_double_click,'fullscreen':self.toggle_fullscreen,'mute':self.toggle_mute,
            'volume-up':lambda:self.step_volume(1),'volume-down':lambda:self.step_volume(-1),
            'pause':lambda:self.command('cycle','pause'),'seek-back':lambda:self.command('seek',-10),
            'seek-forward':lambda:self.command('seek',10),'previous':lambda:self.play_neighbor('previous'),
            'next':lambda:self.play_neighbor('next'),'browser':self.toggle_player_browser,'aspect':self.cycle_aspect,
            'escape':self.player_escape,'quit':self.request_close,'search':self.focus_player_search}
        callback=actions.get(action)
        if callback:callback()

    def focus_player_search(self):
        if hasattr(self,'browser_search'):
            if not self.player_browser_visible():self.toggle_player_browser()
            self.browser_search.grab_focus()

    def choose_close_action(self,downloads):
        message='Quitter TunPlayer ?'
        details='Pour arrêter uniquement la lecture, choisissez « Fermer le contenu ». '
        if self.recording:details+='L’enregistrement sera arrêté. '
        if downloads:details+='Quitter mettra les téléchargements en pause ; fermer le contenu les laisse continuer.'
        if not self.current:details='Les téléchargements seront mis en pause si vous quittez l’application.'
        dialog=Gtk.MessageDialog(transient_for=self.window,modal=True,message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,text=message)
        dialog.format_secondary_text(details);dialog.add_button('Annuler',Gtk.ResponseType.CANCEL)
        if self.current:dialog.add_button('Fermer le contenu',101)
        dialog.add_button('Quitter l’application',102);dialog.set_default_response(Gtk.ResponseType.CANCEL)
        try:
            response=dialog.run()
            return 'content' if response==101 else 'quit' if response==102 else 'cancel'
        finally:dialog.destroy()

    def request_close(self,*_):
        if self.closing:return True
        downloads=bool(self.download_manager and any(row['state'] in ('queued','running','pausing') for row in self.download_manager.snapshot()))
        action=self.choose_close_action(downloads) if self.current or self.recording or downloads else 'quit'
        if action=='content':
            if self.recording:self.stop_record()
            self.back_from_playback()
        elif action=='quit':
            self.close()
            if hasattr(self,'window'):self.window.destroy()
        return True
