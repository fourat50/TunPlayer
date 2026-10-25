import io
import json
import socket
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import URLError,HTTPError
from tunplayer.subtitle_subdl import SubDL
from tunplayer.subtitles import SubtitleHTTP,SubtitleError,SubtitleService
from tunplayer.subtitle_ui import refresh_source_checks,connection_message
from tunplayer.jobs import LatestTask
import test_playback_integration as playback
from test_subtitles import QUERY


def account(search=1988,downloads=47):
    return dict(plan={'name':'Free'},usage=dict(search={'remaining':search},downloads={'remaining':downloads}))


class AccountConnection(unittest.TestCase):
    def provider(self,payload):
        self.requests=[]
        def opener(request,**kwargs):self.requests.append(request);return io.BytesIO(json.dumps(payload).encode())
        return SubDL(SubtitleHTTP(opener),{'subdl_api_key':'SUBDL_SECRET','api_key':'OS_SECRET'})

    def test_account_test_authenticates_without_putting_the_key_in_a_url(self):
        result=self.provider(account()).connection();request=self.requests[0]
        self.assertEqual(request.full_url,'https://api.subdl.com/api/v2/me')
        self.assertEqual(request.get_header('Authorization'),'Bearer SUBDL_SECRET');self.assertNotIn('SECRET',request.full_url)
        self.assertEqual(result,dict(connected=True,search_remaining=1988,download_remaining=47))
        self.assertIn('1988',connection_message(result))

    def test_successful_http_response_alone_does_not_validate_a_connection(self):
        for payload in ({},{'status':True},{'error':'SUBDL_SECRET'},dict(account(),status=False)):
            with self.subTest(payload=payload),self.assertRaises(SubtitleError) as error:self.provider(payload).connection()
            self.assertNotIn('SUBDL_SECRET',str(error.exception))

    def test_missing_key_is_rejected_without_a_network_request(self):
        with patch.object(SubtitleHTTP,'json') as request:
            with self.assertRaises(SubtitleError):SubDL(SubtitleHTTP(),{}).connection()
        request.assert_not_called()

    def test_exhausted_quota_is_distinguished_from_an_invalid_key(self):
        result=self.provider(account(0,0)).connection()
        self.assertTrue(result['connected']);self.assertIn('quota épuisé',connection_message(result))

    def test_unrecognized_quota_values_are_not_displayed_as_successful_counts(self):
        result=self.provider(account('secret',True)).connection()
        self.assertIsNone(result['search_remaining']);self.assertIsNone(result['download_remaining'])
        self.assertNotIn('secret',connection_message(result))

    def test_network_dns_and_authentication_failures_are_explicit_and_do_not_validate_the_key(self):
        for failure,text in ((URLError(socket.gaierror(-2,'dns')),'DNS'),(URLError(TimeoutError()),'délai'),
                (HTTPError('https://api.subdl.com/',401,'SECRET',{},None),'identifiants')):
            def opener(*_,error=failure,**kwargs):raise error
            with self.subTest(text=text),self.assertRaises(SubtitleError) as error:
                SubDL(SubtitleHTTP(opener),{'subdl_api_key':'SECRET'}).connection()
            self.assertIn(text,str(error.exception));self.assertNotIn('SECRET',str(error.exception))


class SearchFeedback(unittest.TestCase):
    def test_adding_a_key_while_the_search_is_open_enables_subdl(self):
        state=[False];checks={'subdl':SimpleNamespace(set_active=lambda value:state.__setitem__(0,value))}
        refresh_source_checks(checks,{},dict(subdl_api_key='new'))
        self.assertTrue(state[0])
        refresh_source_checks(checks,dict(subdl_api_key='new'),{})
        self.assertFalse(state[0])

    def test_unchanged_keys_do_not_override_a_manually_unchecked_source(self):
        changed=[];checks={'subdl':SimpleNamespace(set_active=changed.append)}
        refresh_source_checks(checks,dict(subdl_api_key='same'),dict(subdl_api_key='same'))
        self.assertEqual(changed,[])

    def test_fast_provider_results_are_delivered_before_a_slow_provider_finishes(self):
        started=threading.Event();release=threading.Event();delivered=threading.Event();seen=[]
        row=dict(provider='subdl',id='file',language='fr',release='Saga',score=100,hearing=False,machine=False)
        def slow(*_):started.set();release.wait(3);return []
        def fast(*_):started.wait(1);return [row]
        providers={'podnapisi':SimpleNamespace(search=slow),'subdl':SimpleNamespace(search=fast)}
        def progress(result):
            if result['rows']:seen.append(result);delivered.set()
        with patch.object(SubtitleService,'providers',return_value=providers),ThreadPoolExecutor(max_workers=1) as worker:
            future=worker.submit(SubtitleService().search,QUERY,list(providers),threading.Event(),progress)
            try:
                self.assertTrue(delivered.wait(2));self.assertFalse(future.done())
                self.assertEqual(seen[0]['rows'],[row]);self.assertEqual(seen[0]['pending'],['podnapisi'])
            finally:release.set()
            self.assertEqual(future.result(2)['rows'],[row])


class ProgressDelivery(unittest.TestCase):
    setUp=playback.PlaybackIntegration.setUp
    tearDown=playback.PlaybackIntegration.tearDown
    wait=playback.PlaybackIntegration.wait

    def test_cancelled_progress_cannot_overwrite_a_new_search(self):
        task=LatestTask();dialog=object();seen=[];self.app.subtitle_dialogs[dialog]=(task,)
        try:
            self.app.post_subtitle_progress(dialog,task,task.serial,seen.append,'obsolete')
            task.cancel()
            self.app.post_subtitle_progress(dialog,task,task.serial,seen.append,'current')
            self.wait(lambda:seen==['current']);self.assertEqual(seen,['current'])
        finally:task.close();self.app.subtitle_dialogs.clear()

    def test_closed_dialog_drops_queued_updates(self):
        task=LatestTask();dialog=object();seen=[];self.app.subtitle_dialogs[dialog]=(task,)
        try:
            self.app.post_subtitle_progress(dialog,task,task.serial,seen.append,'late')
            self.app.subtitle_dialogs.clear()
            from gi.repository import GLib
            while GLib.MainContext.default().iteration(False):pass
            self.assertEqual(seen,[])
        finally:task.close()
