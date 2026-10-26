import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
from tunplayer.core import Library,parse_m3u
from tunplayer.source_info import account_connection,normalize_account,fetch_account,subscription,safe_location,account_fields

CONFIG={'type':'xtream','server':'https://example.org/iptv','username':'test','password':'PRIVATE'}
PAYLOAD={'user_info':{'auth':1,'status':'Active','exp_date':'1900000000','created_at':'1700000000',
                     'is_trial':'0','active_cons':'1','max_connections':'2','allowed_output_formats':['ts','m3u8'],
                     'password':'PRIVATE','message':'Private provider message'},
         'server_info':{'timezone':'Africa/Tunis','url':'https://example.org/PRIVATE'}}


class SourceAccounts(unittest.TestCase):
    def test_account_request_omits_action_and_encodes_credentials(self):
        with patch('tunplayer.core.read_resource',return_value=json.dumps(PAYLOAD)) as resource:
            account=fetch_account(dict(CONFIG,password='p?&/'),now=100)
        url=resource.call_args.args[0];query=parse_qs(urlsplit(url).query)
        self.assertNotIn('action',query);self.assertEqual(query['password'],['p?&/'])
        self.assertEqual(account['expires_at'],1900000000);self.assertEqual(account['checked_at'],100)
        self.assertEqual(account['formats'],['ts','m3u8']);self.assertTrue(account['authenticated'])

    def test_only_whitelisted_fields_are_stored(self):
        value=json.dumps(normalize_account(PAYLOAD))
        for secret in ('PRIVATE','Private provider message','https://example'):self.assertNotIn(secret,value)

    def test_m3u_xtream_url_is_recognized_without_guessing_other_hosts(self):
        result=account_connection({'type':'m3u','location':'https://example.org/iptv/get.php?username=a%2Fb&password=p%26ss&type=m3u_plus'})
        self.assertEqual(result,{'server':'https://example.org/iptv','username':'a/b','password':'p&ss'})
        for location in ('/tmp/list.m3u','https://example.org/list.m3u?username=a&password=b','https://example.org/get.php'):
            self.assertIsNone(account_connection({'type':'m3u','location':location}))

    def test_network_failure_preserves_verified_expiration_and_uses_safe_error(self):
        old=normalize_account(PAYLOAD,100)
        with patch('tunplayer.core.request_xtream',side_effect=OSError('https://PRIVATE')):
            result=fetch_account(CONFIG,old,200)
        self.assertEqual(result['expires_at'],old['expires_at']);self.assertEqual(result['checked_at'],100)
        self.assertEqual(result['attempted_at'],200);self.assertTrue(result['error']);self.assertNotIn('PRIVATE',json.dumps(result))

    def test_malformed_response_does_not_erase_verified_account(self):
        with patch('tunplayer.core.request_xtream',return_value={'user_info':[]}):
            result=fetch_account(CONFIG,{'expires_at':1900000000},200)
        self.assertEqual(result['expires_at'],1900000000);self.assertTrue(result['error'])

    def test_missing_invalid_and_explicit_unlimited_expiry_are_distinct(self):
        for value in (None,'0','null',''):
            account=normalize_account({'user_info':{'exp_date':value,'auth':1}})
            self.assertEqual(subscription(account)[0],'Sans date limite')
        for user in ({},{'exp_date':'NaN'},{'exp_date':'inf'},{'exp_date':'bad'},{'exp_date':-1}):
            account=normalize_account({'user_info':user})
            self.assertEqual(subscription(account)[1],'unknown');self.assertFalse(account['expiry_unlimited'])

    def test_expired_soon_active_and_disabled_statuses(self):
        self.assertEqual(subscription({'expires_at':999},1000)[1],'expired')
        self.assertEqual(subscription({'expires_at':1001},1000)[1],'soon')
        self.assertEqual(subscription({'expires_at':1000+8*86400},1000)[1],'active')
        self.assertEqual(subscription({'status':'Banned','expires_at':1900000000},1000),('Désactivé','expired'))

    def test_display_hides_url_secrets_but_exposes_account_limits(self):
        config=dict(CONFIG,server='https://user:PRIVATE@example.org/PRIVATE?token=PRIVATE')
        self.assertEqual(safe_location(config),'https://example.org')
        rows=dict(account_fields(config,normalize_account(PAYLOAD),{'live':12,'movie':3}))
        self.assertEqual(rows['Connexions actives / autorisées'],'1 / 2')
        self.assertIn('12 chaînes',rows['Catalogue local']);self.assertNotIn('PRIVATE',str(rows))
        self.assertEqual(safe_location({'type':'m3u','location':'/home/name/list.m3u'}),'list.m3u')

    def test_unsupported_playlist_makes_no_account_request(self):
        with patch('tunplayer.core.request_xtream') as request:
            self.assertEqual(fetch_account({'type':'m3u','location':'https://example.org/list.m3u'}),{})
        request.assert_not_called()

    def test_additive_database_migration_and_stale_response_protection(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'library.sqlite3'
            db=sqlite3.connect(path);db.execute('CREATE TABLE sources(id INTEGER PRIMARY KEY,name TEXT NOT NULL,count INTEGER NOT NULL)')
            db.execute("INSERT INTO sources VALUES(1,'Ancienne',0)");db.commit();db.close()
            library=Library(path)
            try:
                self.assertEqual(library.source_account(1),{})
                self.assertTrue(library.save_source_account(1,{'expires_at':1900000000},{}))
                self.assertFalse(library.save_source_account(1,{'expires_at':2},CONFIG))
                self.assertEqual(library.source_account(1)['expires_at'],1900000000)
                self.assertFalse(library.save_source_account(999,{},{}))
                self.assertNotIn('account',library.sources()[0])
            finally:library.close()

    def test_account_is_independent_of_catalog_refresh_and_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            library=Library(Path(folder)/'library.sqlite3')
            try:
                rows=parse_m3u('#EXTM3U\n#EXTINF:-1,News\nhttps://example.org/live/1.ts')
                identity=library.import_channels('Test',rows,config=CONFIG)
                library.save_source_account(identity,normalize_account(PAYLOAD),CONFIG)
                library.favorite(library.channels()[0]['id'])
                library.refresh_source(identity,rows)
                self.assertEqual(library.source_account(identity)['expires_at'],1900000000)
                self.assertEqual(library.source_counts(identity),{'live':1})
                self.assertEqual(len(library.channels(view='favorites')),1)
            finally:library.close()
