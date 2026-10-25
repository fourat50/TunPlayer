"""Exercise real dialog callbacks with a small widget harness, without a display."""
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch
import test_playback_integration as playback
from tunplayer.subtitles import SubtitleError,private_json,read_json
from tunplayer.visuals import icon_pixbuf


class Widget:
    def __init__(self,text='',**kwargs):
        self.text=text;self.value=0;self.sensitive=True;self.active=False;self.active_id=None;self.events={};self.model=kwargs.get('model');self.selected=None
    def __getattr__(self,name):return lambda *args,**kwargs:None
    def connect(self,event,callback):self.events[event]=callback
    def set_text(self,value):
        self.text=value
        if 'changed' in self.events:self.events['changed'](self)
    def get_text(self):return self.text
    def set_value(self,value):self.value=value
    def get_value_as_int(self):return int(self.value)
    def set_active(self,value):self.active=value
    def get_active(self):return self.active
    def set_active_id(self,value):self.active_id=value;self.active=0
    def get_active_id(self):return self.active_id
    def get_child(self):return self
    def get_content_area(self):return self
    def get_accessible(self):return self
    def set_sensitive(self,value):self.sensitive=value
    def get_sensitive(self):return self.sensitive
    def get_selection(self):return self
    def get_selected(self):return self.model,self.selected
    def select_iter(self,it):self.selected=it


class Store(list):
    def __init__(self,*_):super().__init__()
    def append(self,row):super().append(row);return len(self)-1


class Combo(Widget):
    @classmethod
    def new_with_entry(cls):return cls()


class DialogHarness:
    def __init__(self,run):
        self.buttons={};self.labels=[];self.entries=[];self.trees=[];self.run=run;self.dialog_titles=[]
        def dialog(**kwargs):
            self.dialog_titles.append(kwargs.get('title',''))
            widget=Widget();widget.run=lambda:self.run(self) or -7;return widget
        def entry():
            widget=Widget();self.entries.append(widget);return widget
        def tree(**kwargs):
            widget=Widget(**kwargs);self.trees.append(widget);return widget
        self.gtk=SimpleNamespace(Dialog=dialog,Entry=entry,Box=Widget,ScrolledWindow=Widget,Spinner=Widget,
            CheckButton=lambda label:Widget(text=label),TreeView=tree,CellRendererText=Widget,
            TreeViewColumn=lambda *args,**kwargs:Widget(),ListStore=Store,
            SpinButton=SimpleNamespace(new_with_range=lambda *args:Widget()),ComboBoxText=Combo,
            LinkButton=SimpleNamespace(new_with_label=lambda *args:Widget()),Orientation=SimpleNamespace(VERTICAL=1),
            PolicyType=SimpleNamespace(NEVER=0,AUTOMATIC=1),ResponseType=SimpleNamespace(CLOSE=-7,APPLY=-10))
    def label(self,text='',*args):widget=Widget(text=text);self.labels.append(widget);return widget
    def button(self,text,callback,*args,**kwargs):
        # Decode actual SVG resources: mocking this concealed a missing search icon.
        if kwargs.get('symbol'):icon_pixbuf(kwargs['symbol'])
        widget=Widget(text=text);widget.click=callback;self.buttons[text]=widget;return widget


class SubtitleDialogs(unittest.TestCase):
    setUp=playback.PlaybackIntegration.setUp
    tearDown=playback.PlaybackIntegration.tearDown
    wait=playback.PlaybackIntegration.wait
    add=playback.PlaybackIntegration.add

    def show(self,harness,method):
        self.app.window=Widget()
        with patch('tunplayer.subtitle_ui.Gtk',harness.gtk),patch('tunplayer.app.Gtk',harness.gtk),patch('tunplayer.app.box',side_effect=lambda *a,**k:Widget()),\
                patch('tunplayer.app.label',side_effect=harness.label),patch('tunplayer.app.button',side_effect=harness.button):method()

    def test_online_action_from_audio_dialog_reaches_the_search_window(self):
        row=self.add();self.app.player=playback.FakePlayer();self.app.player.tracks=lambda:[];self.app.play(row)
        def run(harness):return 101 if harness.dialog_titles[-1]=='Audio et sous-titres' else -7
        harness=DialogHarness(run);self.show(harness,self.app.tracks_dialog)
        self.assertEqual(harness.dialog_titles,['Audio et sous-titres','Rechercher des sous-titres'])
        self.assertIn('Rechercher',harness.buttons);self.assertEqual(self.app.subtitle_dialogs,{})

    def test_real_search_button_uses_a_key_added_without_reopening_the_search(self):
        row=self.add();self.app.player=playback.FakePlayer();self.app.play(row);calls=[]
        def configure():private_json(self.app.subtitle_settings_path,{'subdl_api_key':'TEST_KEY'})
        def search(service,query,enabled,cancel,progress=None):
            calls.append((service.settings,query,enabled));return dict(rows=[],errors={})
        def run(harness):
            harness.buttons['Configurer'].click();harness.buttons['Rechercher'].click()
            self.wait(lambda:bool(calls) and harness.buttons['Rechercher'].get_sensitive())
            self.assertIn('subdl',calls[0][2]);self.assertEqual(calls[0][0]['subdl_api_key'],'TEST_KEY')
            self.assertEqual(calls[0][1]['language'],'fr')
            self.assertTrue(any('Aucun résultat' in label.text for label in harness.labels))
        with patch.object(self.app,'configure_subtitle_sources',side_effect=configure),patch('tunplayer.subtitle_ui.SubtitleService.search',new=search):
            self.show(DialogHarness(run),self.app.search_subtitles)

    def test_successful_account_test_button_saves_the_tested_key(self):
        private_json(self.app.subtitle_settings_path,{'subdl_api_key':'NEW_KEY'})
        def run(harness):
            harness.buttons['Tester la connexion SubDL'].click()
            self.wait(lambda:any('Clé SubDL validée' in label.text for label in harness.labels))
            self.assertEqual(read_json(self.app.subtitle_settings_path)['subdl_api_key'],'NEW_KEY')
        with patch('tunplayer.subtitle_subdl.SubDL.connection',return_value=dict(connected=True,search_remaining=40,download_remaining=20)):
            self.show(DialogHarness(run),self.app.configure_subtitle_sources)

    def test_search_dialog_shows_fast_results_while_another_source_is_still_running(self):
        row=self.add();self.app.player=playback.FakePlayer();self.app.play(row)
        private_json(self.app.subtitle_settings_path,{'subdl_api_key':'TEST_KEY'})
        started=threading.Event();release=threading.Event()
        result=dict(provider='subdl',id='file',language='fr',release='Film',score=60,hearing=False,machine=False)
        def slow(*_):started.set();release.wait(3);return []
        def fast(*_):started.wait(1);return [result]
        providers={'podnapisi':SimpleNamespace(search=slow),'subdl':SimpleNamespace(search=fast)}
        def run(harness):
            harness.buttons['Rechercher'].click()
            self.wait(lambda:any('1 résultat(s). Recherche en cours : Podnapisi.' in label.text for label in harness.labels))
            self.assertTrue(harness.buttons['Télécharger et activer'].get_sensitive())
            self.assertFalse(harness.buttons['Rechercher'].get_sensitive())
            release.set();self.wait(lambda:harness.buttons['Rechercher'].get_sensitive())
        try:
            with patch('tunplayer.subtitle_ui.SubtitleService.providers',return_value=providers):
                self.show(DialogHarness(run),self.app.search_subtitles)
        finally:release.set()

    def test_failed_account_test_button_displays_failure_without_claiming_success(self):
        private_json(self.app.subtitle_settings_path,{'subdl_api_key':'BAD_KEY'})
        def run(harness):
            harness.buttons['Tester la connexion SubDL'].click()
            self.wait(lambda:any('Échec du test' in label.text for label in harness.labels))
            self.assertFalse(any('Clé SubDL validée' in label.text for label in harness.labels))
        with patch('tunplayer.subtitle_subdl.SubDL.connection',side_effect=SubtitleError('Clé refusée.')):
            self.show(DialogHarness(run),self.app.configure_subtitle_sources)

    def test_editing_a_key_during_the_test_cannot_save_or_validate_the_old_response(self):
        private_json(self.app.subtitle_settings_path,{'subdl_api_key':'OLD_KEY'})
        started=threading.Event();release=threading.Event()
        def connection():started.set();release.wait(2);return dict(connected=True,search_remaining=40,download_remaining=20)
        def run(harness):
            harness.buttons['Tester la connexion SubDL'].click();self.assertTrue(started.wait(1))
            entry=next(entry for entry in harness.entries if entry.get_text()=='OLD_KEY');entry.set_text('NEW_KEY')
            release.set();self.wait(lambda:all(task.future is None or task.future.done() for tasks in self.app.subtitle_dialogs.values() for task in tasks))
            self.assertFalse(any('Clé SubDL validée' in label.text for label in harness.labels))
            self.assertEqual(read_json(self.app.subtitle_settings_path)['subdl_api_key'],'OLD_KEY')
        try:
            with patch('tunplayer.subtitle_subdl.SubDL.connection',side_effect=connection):
                self.show(DialogHarness(run),self.app.configure_subtitle_sources)
        finally:release.set()

    def test_a_successful_api_test_does_not_claim_that_an_unwritable_profile_was_saved(self):
        private_json(self.app.subtitle_settings_path,{'subdl_api_key':'OLD_KEY'})
        def run(harness):
            next(entry for entry in harness.entries if entry.get_text()=='OLD_KEY').set_text('NEW_KEY')
            harness.buttons['Tester la connexion SubDL'].click()
            self.wait(lambda:any('Clé valide, mais' in label.text for label in harness.labels))
            self.assertFalse(any('Clé SubDL validée · configuration enregistrée' in label.text for label in harness.labels))
            self.assertEqual(read_json(self.app.subtitle_settings_path)['subdl_api_key'],'OLD_KEY')
        with patch('tunplayer.subtitle_subdl.SubDL.connection',return_value=dict(connected=True)),\
                patch('tunplayer.subtitle_ui.private_json',side_effect=PermissionError('profile unavailable')):
            self.show(DialogHarness(run),self.app.configure_subtitle_sources)
