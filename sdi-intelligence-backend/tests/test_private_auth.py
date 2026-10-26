import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
from dataclasses import replace
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from private_auth import PrivateAuth, Settings, Store, COOKIE, FLOW_COOKIE, CALLBACK, SCOPES
from private_email_integration import install
from private_email_routes import make_router
from private_email import Policy

TENANT = "f0b45992-4294-4922-9ad5-8299efe0f57f"
OWNER = "5acf6b37-147f-4468-bdb1-ecc3da1f1076"
CLIENT = "267fa0cc-38f7-4cc2-9a2d-7ecc436ad23b"
ORIGIN = "https://private.example.test"


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = Settings(TENANT, CLIENT, OWNER, ORIGIN, "test-not-real-secret",
                                 Fernet.generate_key().decode(), str(Path(self.temp.name)/"sessions.db"))
        self.claims = {"tid":TENANT,"oid":OWNER,"aud":CLIENT,"exp":time.time()+3600}
        self.msal = Mock()
        self.msal.initiate_auth_code_flow.return_value = {
            "state":"one-use-state", "auth_uri":"https://login.microsoftonline.com/test"}
        self.msal.acquire_token_by_auth_code_flow.side_effect = lambda *a: {"id_token_claims":dict(self.claims)}
        self.msal.get_accounts.return_value = [{"local_account_id":OWNER,"realm":TENANT}]
        self.msal.acquire_token_silent.return_value = {"access_token":"test-token", "scope":"User.Read Mail.ReadWrite"}
        self.auth = PrivateAuth(self.settings, factory=lambda cache:self.msal)
        app = FastAPI()
        app.include_router(self.auth.router)
        app.include_router(make_router(self.auth, Policy(TENANT,OWNER,True), None, ORIGIN))
        self.client = TestClient(app, base_url=ORIGIN, follow_redirects=False)
        self.addCleanup(self.client.close)

    def login(self):
        return self.client.get('/api/private-email/auth/login')

    def callback(self):
        return self.client.get(CALLBACK+'?state=one-use-state&code=test')

    def test_callback_owner_sets_private_secure_cookie(self):
        self.assertEqual(self.login().status_code,302)
        r = self.callback()
        self.assertEqual(r.status_code,302)
        cookie = r.headers.get_list('set-cookie')[0]
        for expected in (COOKIE, 'HttpOnly', 'Secure', 'SameSite=lax', 'Path=/'):
            self.assertIn(expected,cookie)
        self.assertEqual(self.client.get('/api/private-email/workspace').status_code,200)

    def test_fixed_callback_and_scopes(self):
        self.login()
        args = self.msal.initiate_auth_code_flow.call_args.kwargs
        self.assertEqual(args['redirect_uri'],ORIGIN+CALLBACK)
        self.assertEqual(args['scopes'],SCOPES)

    def test_wrong_owner_tenant_audience_and_expired_denied(self):
        for key,value in [('oid','other'),('tid','other'),('aud','other'),('exp',0)]:
            with self.subTest(key=key):
                old = self.claims[key]
                self.claims[key] = value
                self.login()
                self.assertEqual(self.callback().status_code,403)
                self.assertNotIn(COOKIE,self.client.cookies)
                self.claims[key] = old

    def test_callback_replay_denied(self):
        self.login()
        self.assertEqual(self.callback().status_code,302)
        self.assertEqual(self.callback().status_code,400)
        self.assertEqual(self.msal.acquire_token_by_auth_code_flow.call_count,1)

    def test_other_browser_denied_before_exchange(self):
        self.login()
        self.client.cookies.clear()
        self.assertEqual(self.callback().status_code,400)
        self.msal.acquire_token_by_auth_code_flow.assert_not_called()

    def test_missing_state_denied(self):
        self.assertEqual(self.client.get(CALLBACK).status_code,400)

    def test_msal_rejection_does_not_leak_error(self):
        self.login()
        self.msal.acquire_token_by_auth_code_flow.side_effect = ValueError('secret-code')
        r = self.callback()
        self.assertEqual(r.status_code,401)
        self.assertNotIn('secret-code',r.text)

    def test_host_and_forwarded_header_cannot_change_callback(self):
        r = self.client.get('/api/private-email/auth/login',headers={'Host':'evil.test','X-Forwarded-Host':url_host()})
        self.assertEqual(r.status_code,403)
        self.msal.initiate_auth_code_flow.assert_not_called()

    def test_shared_cookie_and_machine_key_do_not_authenticate(self):
        r = self.client.get('/api/private-email/workspace',headers={'Cookie':'sdi_session=old','X-SDI-Key':'key'})
        self.assertEqual(r.status_code,403)

    def test_draft_routes_are_absent_until_drafts_are_switched_on(self):
        """Drafting is its own switch. With it off the routes still refuse, so a
        portal that has not been asked for drafts cannot be talked into one."""
        self.login(); self.callback()
        for path,payload in [('proposals',{'message_id':'x','body':'reply'}),('confirm',{'proposal_id':'x','digest':'y'})]:
            r = self.client.post('/api/private-email/'+path,json=payload,
                                 headers={'Origin':ORIGIN,'X-SDI-Private-Action':'1'})
            self.assertEqual(r.status_code,403)
            self.assertIn('disabled',r.text)

    def test_the_app_asks_for_drafting_but_never_for_sending(self):
        """Mail.ReadWrite puts a draft in the owner's Drafts folder. Mail.Send would
        post it, and is the difference between an assistant that writes for you and
        one that writes AS you. It is never requested, and a token carrying it is
        refused however it came to be granted."""
        from private_auth import NEVER
        self.assertIn('Mail.ReadWrite', SCOPES)
        self.assertNotIn('Mail.Send', SCOPES)
        self.assertIn('Mail.Send', NEVER)
        self.login()
        self.assertEqual(self.msal.initiate_auth_code_flow.call_args.kwargs['scopes'], SCOPES)
        # No route can send, whatever the token says.
        from private_email import GraphMailbox
        self.assertFalse([m for m in dir(GraphMailbox) if 'send' in m.lower()])

    def test_drafts_need_somewhere_to_keep_pending_approvals(self):
        """SDI_PRIVATE_DRAFTS=yes with nowhere to put them must stop the service
        starting, not mount a write path whose approvals vanish on restart."""
        env = {'SDI_PRIVATE_'+k: v for k, v in zip(
            ('ENABLED','TENANT_ID','CLIENT_ID','OWNER_ID','ORIGIN','CLIENT_SECRET',
             'ENCRYPTION_KEY','SESSION_DB'),
            ('yes',TENANT,CLIENT,OWNER,ORIGIN,'test-secret',
             self.settings.encryption_key,self.settings.database))}
        env['SDI_PRIVATE_DRAFTS'] = 'yes'
        with self.assertRaises(RuntimeError) as caught:
            install(FastAPI(), env, factory=lambda cache: self.msal)
        self.assertIn('SDI_PRIVATE_DRAFT_DB', str(caught.exception))
        # With a path, it mounts, and the draft routes are there.
        env['SDI_PRIVATE_DRAFT_DB'] = str(Path(self.temp.name)/'drafts.db')
        app = FastAPI()
        install(app, env, factory=lambda cache: self.msal)
        with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
            client.get('/api/private-email/auth/login')
            client.get(CALLBACK + '?state=one-use-state&code=x')
            # Present now: refused for a reason about the request, not "disabled".
            r = client.post('/api/private-email/proposals',
                            json={'message_id': 'x', 'body': 'hello'},
                            headers={'Origin': ORIGIN, 'X-SDI-Private-Action': '1'})
            self.assertNotEqual(r.status_code, 404, 'the draft route is mounted')
            self.assertNotIn('disabled', r.text)

    def test_expired_session_denied(self):
        self.login(); self.callback()
        with self.auth.store.connection() as db:
            db.execute('UPDATE private_sessions SET expires=0')
        self.assertEqual(self.client.get('/api/private-email/workspace').status_code,403)

    def test_logout_csrf_then_local_revocation(self):
        self.login(); self.callback()
        path='/api/private-email/auth/logout'
        self.assertEqual(self.client.post(path,headers={'Origin':'https://evil.test'}).status_code,403)
        self.assertEqual(self.client.post(path,headers={'Origin':ORIGIN,'X-SDI-Private-Action':'1'}).status_code,200)
        self.assertEqual(self.client.get('/api/private-email/workspace').status_code,403)

    def test_encrypted_and_isolated_store(self):
        self.auth.store.put('test',{'secret':'do-not-store-plaintext'},time.time()+60)
        self.assertNotIn(b'do-not-store-plaintext',Path(self.settings.database).read_bytes())
        other = Store(str(Path(self.temp.name)/'other.db'),self.settings.encryption_key)
        self.assertIsNone(other.get('test'))
        wrong_key = Store(self.settings.database,Fernet.generate_key().decode())
        self.assertIsNone(wrong_key.get('test'))

    def test_config_rejects_untrusted_origin_and_missing_settings(self):
        for change in ({'origin':'http://private.test'}, {'origin':ORIGIN+'/callback'},
                       {'origin':'https://name:password@private.test'}, {'owner':''}, {'credential':''}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(self.settings,**change).validate()

    def test_disabled_integration_mounts_nothing(self):
        app=FastAPI()
        self.assertIsNone(install(app,{}))
        self.assertFalse(any('/private-email' in r.path for r in app.routes))

    def test_enabled_integration_mounts_actual_readonly_routes(self):
        env={'SDI_PRIVATE_ENABLED':'yes'}
        for key,value in zip(('TENANT_ID','CLIENT_ID','OWNER_ID','ORIGIN','CLIENT_SECRET','ENCRYPTION_KEY','SESSION_DB'),
                             (TENANT,CLIENT,OWNER,ORIGIN,'test-secret',self.settings.encryption_key,self.settings.database)):
            env['SDI_PRIVATE_'+key]=value
        app=FastAPI()
        install(app,env,factory=lambda cache:self.msal)
        with TestClient(app,base_url=ORIGIN,follow_redirects=False) as client:
            self.assertEqual(client.get('/api/private-email/auth/login').status_code,302)
            self.assertEqual(client.get(CALLBACK+'?state=one-use-state&code=x').status_code,302)
            r=client.get('/api/private-email/workspace')
            self.assertEqual(r.status_code,200)
            self.assertIn('Read-only pilot',r.text)
            self.assertNotIn('Confirm — save',r.text)

    def test_entra_may_return_a_scope_in_either_form(self):
        """Entra returns a granted scope as "Mail.ReadWrite" or as the full
        "https://graph.microsoft.com/Mail.ReadWrite", and which one is not ours to
        decide. Comparing the long form against the short name we asked for made
        every real token look like it lacked the permission - the first live
        sign-in answered "Mailbox consent required" with the consent granted."""
        from starlette.requests import Request
        self.login(); self.callback()
        request = Request({'type':'http','headers':[(b'host',url_host().encode()),
                           (b'cookie',(COOKIE+'='+self.client.cookies[COOKIE]).encode())]})
        for granted in ('User.Read Mail.ReadWrite',
                        'https://graph.microsoft.com/User.Read '
                        'https://graph.microsoft.com/Mail.ReadWrite',
                        'https://graph.microsoft.com/Mail.ReadWrite User.Read'):
            with self.subTest(granted=granted):
                self.msal.acquire_token_silent.return_value = {
                    'access_token':'test-token','scope':granted}
                self.assertEqual(self.auth.graph_token(request), 'test-token')
        # And the refusal still works in the long form.
        self.msal.acquire_token_silent.return_value = {
            'access_token':'x','scope':'https://graph.microsoft.com/Mail.ReadWrite '
                                       'https://graph.microsoft.com/Mail.Send User.Read'}
        self.assertIsNone(self.auth.graph_token(request))

    def test_the_permissions_are_asked_for_both_ways_microsoft_writes_them(self):
        """26 October 2026, the live sign-in: a fresh, successful sign-in, and a
        second later "holds []" in the log - MSAL answering that it had no token
        at all. It files a token under the scope strings Entra replied with, and
        matches a silent request against them literally, so asking for
        "Mail.ReadWrite" finds nothing when the cache says
        "https://graph.microsoft.com/Mail.ReadWrite". That comparison is inside
        MSAL and out of our reach, so both forms get asked."""
        from starlette.requests import Request
        self.login(); self.callback()
        request = Request({'type':'http','headers':[(b'host',url_host().encode()),
                           (b'cookie',(COOKIE+'='+self.client.cookies[COOKIE]).encode())]})

        answers = {}   # only the fully-qualified form is known to this cache
        def silent(asked, account=None):
            answers[tuple(asked)] = True
            if all(s.startswith('https://graph.microsoft.com/') for s in asked):
                return {'access_token':'test-token',
                        'scope':'https://graph.microsoft.com/User.Read '
                                'https://graph.microsoft.com/Mail.ReadWrite'}
            return None
        self.msal.acquire_token_silent.side_effect = silent

        self.assertEqual(self.auth.graph_token(request), 'test-token')
        self.assertIn(('User.Read','Mail.ReadWrite'), answers, answers)
        self.assertIn(('https://graph.microsoft.com/User.Read',
                       'https://graph.microsoft.com/Mail.ReadWrite'), answers, answers)

        # The mirror case: a cache that only knows the short names still works,
        # and is not asked twice for nothing.
        answers.clear()
        self.msal.acquire_token_silent.side_effect = lambda asked, account=None: (
            {'access_token':'short-form','scope':'User.Read Mail.ReadWrite'}
            if not any(s.startswith('https://') for s in asked) else None)
        self.assertEqual(self.auth.graph_token(request), 'short-form')

    def test_no_token_at_all_is_logged_as_itself_not_as_missing_consent(self):
        """"holds []" read as a permission problem and cost an afternoon in Entra.
        Nothing from the cache is a different fault from a token lacking a scope,
        and the log has to say which, with MSAL's own reason."""
        from starlette.requests import Request
        import io, contextlib
        self.login(); self.callback()
        request = Request({'type':'http','headers':[(b'host',url_host().encode()),
                           (b'cookie',(COOKIE+'='+self.client.cookies[COOKIE]).encode())]})
        self.msal.acquire_token_silent.return_value = None
        self.msal.acquire_token_silent_with_error.return_value = {
            'error':'invalid_grant', 'error_description':'AADSTS50173 token expired'}

        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            self.assertIsNone(self.auth.graph_token(request))
        said = log.getvalue()
        self.assertIn('no token from the cache', said)
        self.assertIn('invalid_grant', said)
        self.assertIn('AADSTS50173', said)
        self.assertNotIn('test-not-real-secret', said)
        self.assertNotIn(self.client.cookies[COOKIE], said)

    def test_a_probe_that_itself_fails_says_nothing_and_breaks_nothing(self):
        from starlette.requests import Request
        import io, contextlib
        self.login(); self.callback()
        request = Request({'type':'http','headers':[(b'host',url_host().encode()),
                           (b'cookie',(COOKIE+'='+self.client.cookies[COOKIE]).encode())]})
        self.msal.acquire_token_silent.return_value = None
        self.msal.acquire_token_silent_with_error.side_effect = RuntimeError("offline")
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            self.assertIsNone(self.auth.graph_token(request))
        self.assertIn('RuntimeError: offline', log.getvalue())

    def test_graph_cache_wrong_account_or_broad_scope_denied(self):
        from starlette.requests import Request
        self.login(); self.callback()
        request=Request({'type':'http','headers':[(b'host',url_host().encode()),(b'cookie',(COOKIE+'='+self.client.cookies[COOKIE]).encode())]})
        self.assertEqual(self.auth.graph_token(request),'test-token')
        self.msal.get_accounts.return_value=[{'local_account_id':'other','realm':TENANT}]
        self.assertIsNone(self.auth.graph_token(request))
        self.msal.get_accounts.return_value=[{'local_account_id':OWNER,'realm':TENANT}]
        self.msal.acquire_token_silent.return_value={'access_token':'too-broad','scope':'User.Read Mail.ReadWrite Mail.Send'}
        self.assertIsNone(self.auth.graph_token(request))


    # ── THE THREE THINGS THE REVIEW ASKED FOR, 26 OCTOBER 2026 ──────────────────

    def test_the_login_flow_round_trips_through_real_sqlite(self):
        """BEGIN IMMEDIATE inside sqlite3's own context manager is driver behaviour,
        not ours, and it sits on the one path every sign-in takes. Nothing here is
        mocked below the store, so running this suite on the SERVER's Python is what
        proves the server's Python can sign somebody in."""
        import sqlite3
        self.assertEqual(self.login().status_code, 302, 'login writes the flow row')
        self.assertEqual(self.callback().status_code, 302, 'callback consumes it')
        # Single use: the same state cannot be replayed, and the failure is the
        # intended 400 rather than a sqlite transaction error.
        replay = self.client.get(CALLBACK + '?state=one-use-state&code=test')
        self.assertEqual(replay.status_code, 400, replay.text)
        # And the store itself, directly, on this interpreter's sqlite3.
        store = Store(self.settings.database, self.settings.encryption_key)
        store.put('flow:direct', {'flow': {}, 'browser': 'n'}, time.time() + 60)
        self.assertIsNotNone(store.get('flow:direct', consume=True))
        self.assertIsNone(store.get('flow:direct', consume=True))
        self.assertGreaterEqual(sqlite3.sqlite_version_info, (3, 0, 0))

    def test_graph_refusing_access_is_not_reported_as_an_outage(self):
        """401 and 403 are what a missing consent looks like. Calling that "Graph
        unavailable" sends somebody to check the network when the answer is in Entra."""
        import httpx as _httpx
        from private_email_routes import make_router as _make
        self.login(); self.callback()

        for status in (401, 403):
            with self.subTest(status=status):
                class _Client:
                    def __init__(self, *a, **k): pass
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                    def request(self, method, url, **kw):
                        return _httpx.Response(status, json={'error': {'code': 'x',
                                               'message': 'tenant-specific detail'}},
                                               request=_httpx.Request(method, url))
                real, _httpx.Client = _httpx.Client, _Client
                try:
                    r = self.client.get('/api/private-email/review')
                finally:
                    _httpx.Client = real
                self.assertEqual(r.status_code, 403, r.text)
                detail = r.json()['detail']
                self.assertIn('consent', detail.lower())
                self.assertNotIn('unavailable', detail.lower())
                # Graph's own body never reaches the browser.
                self.assertNotIn('tenant-specific detail', r.text)

    def test_a_page_that_was_not_deployed_stops_the_service_starting(self):
        """The draft UI is not in this release. The flag is the only thing between a
        reader and a page with a Save Draft button, so asking for drafts without the
        page must stop the service starting, not fail later at a 404."""
        import private_email_routes as _routes
        from private_email_routes import make_router as _make, DRAFT_PAGE, READONLY_PAGE
        # Beside the MODULE, not beside this test: they are deployed to the service's
        # own folder and the test lives in tests/.
        here = Path(_routes.__file__).parent
        self.assertTrue((here / READONLY_PAGE).is_file())
        self.assertTrue((here / DRAFT_PAGE).is_file(), 'the draft UI ships now that drafting does')
        # A page that is not deployed alongside the code stops the service starting,
        # rather than mounting the routes and failing later at a 404.
        empty = Path(self.temp.name) / 'no-pages'; empty.mkdir()
        for drafting in (True, False):
            with self.assertRaises(RuntimeError):
                _make(self.auth, Policy(TENANT, OWNER, True), None, ORIGIN,
                      drafts_enabled=drafting, page_dir=empty)
        _make(self.auth, Policy(TENANT, OWNER, True), None, ORIGIN)


def url_host():
    return 'private.example.test'


if __name__=='__main__':
    unittest.main()
