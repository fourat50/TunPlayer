"""Replay sanitized responses actually received on the user's machine."""
import io
import json
from pathlib import Path
import threading
import unittest
from urllib.request import Request
from tunplayer.subtitles import SubtitleHTTP,SubtitleError,SubtitleRedirect
from tunplayer.subtitle_subdl import SubDL,download_url
from test_subtitles import SRT


class ObservedSubDLResponses(unittest.TestCase):
    def test_observed_inception_and_500_miles_files_are_no_longer_all_rejected(self):
        cases=json.loads((Path(__file__).parent/'fixtures/subdl_redacted_responses.json').read_text())
        for case in cases:
            with self.subTest(title=case['query']['title']):
                def opener(*args,**kwargs):return io.BytesIO(json.dumps(case['response']).encode())
                provider=SubDL(SubtitleHTTP(opener),{'subdl_api_key':'OWN_KEY'})
                rows=provider.search(case['query'],threading.Event())
                self.assertEqual(len(rows),3);self.assertEqual(provider.diagnostic['link'],0)
                for row in rows:
                    self.assertNotIn('api_key',row['download_url']);self.assertNotIn('masqué',row['id'])

    def test_only_known_key_parameter_is_removed_after_validating_the_cdn_origin(self):
        self.assertEqual(download_url('/subtitle/a/b?api_key=RESPONSE_KEY'),'https://dl.subdl.com/subtitle/a/b')
        for url in ('https://evil.example/subtitle/a?api_key=key','/subtitle/a?api_key=key&redirect=evil','/subtitle/a?token=key'):
            with self.subTest(url=url),self.assertRaises(SubtitleError):download_url(url)

    def test_response_key_is_never_used_or_stored_and_own_key_is_sent_by_header(self):
        requests=[]
        def opener(request,**kwargs):requests.append(request);return io.BytesIO(SRT)
        provider=SubDL(SubtitleHTTP(opener),{'subdl_api_key':'OWN_KEY','api_key':'OTHER_PROVIDER_KEY'})
        data,_=provider.download({'download_url':'/subtitle/a/b?api_key=RESPONSE_KEY'})
        self.assertEqual(data,SRT);self.assertEqual(requests[0].full_url,'https://dl.subdl.com/subtitle/a/b')
        self.assertEqual(requests[0].get_header('X-api-key'),'OWN_KEY')
        self.assertNotIn('RESPONSE_KEY',str(requests[0].headers));self.assertNotIn('OTHER_PROVIDER_KEY',str(requests[0].headers))

    def test_cdn_authentication_header_is_not_forwarded_after_a_redirect(self):
        request=Request('https://dl.subdl.com/subtitle/a',headers={'X-API-Key':'OWN_KEY'})
        redirected=SubtitleRedirect().redirect_request(request,None,302,'redirect',{},'https://files.subdl.com/file')
        self.assertIsNone(redirected.get_header('X-api-key'))
