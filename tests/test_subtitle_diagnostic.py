import io
import json
import unittest
from urllib.error import HTTPError
from scripts.diagnose_subtitles import scrub,response_excerpt,attempt
from tunplayer.subtitles import SubtitleHTTP
from tunplayer.subtitle_subdl import SubDL


class SubtitleDiagnostic(unittest.TestCase):
    def test_secrets_are_removed_from_nested_fields_and_urls(self):
        value={'api_key':'SECRET','nested':[{'authorization':'Bearer SECRET','X-API-Key':'SECRET'}],
               'message':'Invalid credential SECRET','url':'https://user:pass@api.subdl.com/a?api_key=SECRET&other=token'}
        clean=json.dumps(scrub(value,['SECRET']))
        for secret in ('SECRET','user:pass','other=token'):self.assertNotIn(secret,clean)

    def test_account_identity_is_not_included_in_response_examples(self):
        result=response_excerpt({'email':'private@example.org','username':'personal-name','usage':{'search':{'remaining':20}},'plan':{'name':'Free'}})
        self.assertNotIn('private@example.org',json.dumps(result));self.assertNotIn('personal-name',json.dumps(result))

    def test_response_samples_are_bounded_and_sensitive_fields_are_masked(self):
        result=response_excerpt({'subtitles':[{'language':'FR','api_key':'SECRET'} for _ in range(50)]},['SECRET'])
        self.assertEqual(result['schema']['subtitles']['count'],50);self.assertEqual(len(result['subtitle_examples']),3)
        self.assertNotIn('SECRET',json.dumps(result))

    def test_real_backend_and_transport_parser_produce_a_useful_redacted_report(self):
        payload={'status':True,'results':[{'type':'movie','name':'Test'}],
                 'subtitles':[{'language':'FR','name':'Test.srt','url':'/subtitle/test.zip'}]}
        class HTTP(SubtitleHTTP):
            def __init__(self):
                def opener(request,**kwargs):
                    result=io.BytesIO(json.dumps(payload).encode());result.status=200;return result
                super().__init__(opener=opener)
        result=attempt('Test',dict(title='Test',kind='movie',year=0,season=0,episode=0,language='fr'),SubDL,HTTP,{'subdl_api_key':'SECRET'})
        self.assertTrue(result['ok']);self.assertEqual(result['count'],1)
        self.assertEqual(result['requests'][0]['http_status'],200)
        self.assertTrue(result['requests'][0]['authentication_present']);self.assertNotIn('SECRET',json.dumps(result))

    def test_http_error_status_and_redacted_body_are_preserved(self):
        class HTTP(SubtitleHTTP):
            def __init__(self):
                def opener(request,**kwargs):
                    raise HTTPError(request.full_url,401,'Unauthorized',{},io.BytesIO(b'{"error":"Invalid SECRET"}'))
                super().__init__(opener=opener)
        result=attempt('Compte',None,SubDL,HTTP,{'subdl_api_key':'SECRET'})
        self.assertFalse(result['ok']);self.assertEqual(result['requests'][0]['http_status'],401)
        self.assertNotIn('SECRET',json.dumps(result))

    def test_download_probe_validates_subtitle_without_exposing_credentials(self):
        payload={'status':True,'results':[{'type':'movie','name':'Test'}],
                 'subtitles':[{'language':'EN','name':'Test.srt','url':'/subtitle/test.srt?api_key=SECRET'}]}
        class HTTP(SubtitleHTTP):
            def __init__(self):
                def opener(request,**kwargs):
                    data=(b'1\n00:00:01,000 --> 00:00:02,000\nHello\n' if request.host=='dl.subdl.com'
                          else json.dumps(payload).encode())
                    result=io.BytesIO(data);result.status=200;return result
                super().__init__(opener=opener)
        result=attempt('Test',dict(title='Test',kind='movie',year=0,season=0,episode=0,language='all'),SubDL,HTTP,{'subdl_api_key':'SECRET'},download=True)
        self.assertTrue(result['download_probe']['ok']);self.assertGreater(result['download_probe']['bytes'],0)
        self.assertTrue(result['requests'][-1]['authentication_present'])
        self.assertNotIn('SECRET',json.dumps(result));self.assertNotIn('Hello',json.dumps(result))
