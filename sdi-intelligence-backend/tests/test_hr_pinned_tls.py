"""Pinned certificate = trust anchor, on every Python version.

InVentry's certificate is issued by a signer we do not hold. Pinning just the
certificate verified on the desktop (Python 3.14, which enables
VERIFY_X509_PARTIAL_CHAIN by default) and failed on SDI-App01 with "unable to
get local issuer certificate" (older Python, 19 Oct 2026). These tests do a
real TLS handshake against a local server presenting a leaf signed by an issuer
the client never sees - InVentry's shape - so they reproduce the server's
failure on any interpreter old enough to have it.

The keys below are throwaway test material generated for this file. They
protect nothing.
"""
import http.server
import ssl
import sys
import threading
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hr_inventry_api as api  # noqa: E402

LEAF_SIGNED_BY_UNKNOWN_ISSUER = """-----BEGIN CERTIFICATE-----
MIICtTCCAZ0CFB2BvdJtQ5Ew3WP4ZQX/VaeZfgSXMA0GCSqGSIb3DQEBCwUAMBYx
FDASBgNVBAMMC1Rlc3QgSXNzdWVyMCAXDTI2MTAxOTE2NTAzM1oYDzIxMjYwOTI1
MTY1MDMzWjAWMRQwEgYDVQQDDAtJblZlbnRyeS1QQzCCASIwDQYJKoZIhvcNAQEB
BQADggEPADCCAQoCggEBALCrgwHxTKj5CMnZks1th+MoC7r1kbYBT+yuArMyrnuh
PZQeKv0wwdiS01MuLInx74vUuO+3Ro3h3Clwx6Mam9BfNMUouOxuwd9HXj8WSgKC
EqfDiGBXssVQFeywKlE5NB9aGQsIn1gqizFhYI5ltkSSV+l+0Sy4bMrmUenyUUam
zChT3GLcWdc+/n/WT198tq/GkYg4mBeczxrf6IrLRNiH2G76icHg+u/t2xJVM5Kz
pNPi1sHV+24eIKHo+w/szGlirfCp3BTxWQ8CQ4FR7+i1ZNtSWAF6hZ+DSzlUNrpG
0Kmbw9ZR2qMktQlIZmKcPYnKjiZuX7LOi28NMPa2Ne0CAwEAATANBgkqhkiG9w0B
AQsFAAOCAQEANpJLmu/PxXZQru+mAkibuBQxm/61PyZGPBo4VzAb4vJIVaVzc2u8
Kkvr1Qw2DF87aNCpJeC3i0Dp1AInL2aNKjGglU0qqOyLoHRe5KzalnmYKmnUoJTk
EBqR9YPfhTFk/L5ReDjLOM60Gh3drDOXICx2Jt4HYuUx1M1wlhsHg9wa4EJ6v2df
/q4guAvaEf3R4lQC+MQ2UVUtFC3LsehLzIIu8JYp/QSGWFA+3TgTCR8aOw8bs2G5
MRJ6wzmKMxjMOgU8eMNtj8nQ1f8HWOkwEOeOeNAueuSFYQ8nRw3R7Lh5LH4vbkG6
Z6rMvRkNcmj2+NiisMJJWeQOtNZCIVKpAg==
-----END CERTIFICATE-----
"""
LEAF_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCwq4MB8Uyo+QjJ
2ZLNbYfjKAu69ZG2AU/srgKzMq57oT2UHir9MMHYktNTLiyJ8e+L1Ljvt0aN4dwp
cMejGpvQXzTFKLjsbsHfR14/FkoCghKnw4hgV7LFUBXssCpROTQfWhkLCJ9YKosx
YWCOZbZEklfpftEsuGzK5lHp8lFGpswoU9xi3FnXPv5/1k9ffLavxpGIOJgXnM8a
3+iKy0TYh9hu+onB4Prv7dsSVTOSs6TT4tbB1ftuHiCh6PsP7MxpYq3wqdwU8VkP
AkOBUe/otWTbUlgBeoWfg0s5VDa6RtCpm8PWUdqjJLUJSGZinD2Jyo4mbl+yzotv
DTD2tjXtAgMBAAECggEAHOOy/NSVRVVR0VYViiekzqm7/1LMRL+irvCGiwCY5SkI
/YlQXM5GCJD74xB8IoOQOSSsKDDnZeie3JzvXFXL0G9dHPdrg+gZplYQjI7rw8y6
2bmg+aYlmtvddfKZvOX2hsDwMuxySBPO5qCGjkqGG2D15L4C3QX8blJq5y9jiIKU
70kv5nTUkIQfbCrn60F9z7ZNZu3sWuzrDtOkkkMdWi93SM9nn6bf7BXAMkJjsy7J
G5B8QyUVPeyvRZMSSgX5slh4p9vOpbLYU5KDebqkEX9ZSbE7oITsVzqp/RrnxsQF
O+CUCpZQ3LyMwCi/TcCYwnw7JtA4ohWoIl9+dgNriQKBgQDa+6dpA5uDqwtOv6oc
NSEogrwywQ2EhFSNdbuwc5XcHstRC64qzsuM4ZZqhG7plcevyv5czEDi5LkBcwla
wIXgZN3MR8usWWz/x0KZTd65y0Hie/VBDZIIrMcfVdLQQOOu176g2GHCPxitTDk7
QqH4Em5XQ9zrH37y2xselxj2eQKBgQDOiMnHzmLMdDghkb0hnClUX9vyjHG2RF5D
dGfOY6UwgqGsdhBM78+lUk3m1a4ziysMye8Rnr3qucH4GjVVQ6Ycqd3en7zYSPHz
l3ppsSm5rIwc5ucZmSm8Ln8Ppx6aX1SYq5Hzn9dTJc2ozaGpWSfRtzyMPDdgJ+2b
3J2EzVJuFQKBgF3rSOXVUkGqfnML6R2n+8ywJZ9vBSksyEbTk+gd6sw5uOHNrKlX
gB2wMx8EJb2xK6/N1EJgqAOoLWDdwclWgRS4rhgLQuNshz88auftafUto9hLaei4
tUVbNRvPZ1dCPWSjy3KY23TAMwlAg9tSvLz0yrZKuNlu7LekGYGJNH+hAoGAb0BT
oONVaNh5m+uLO12JDcANFFv+rLWrKR69A/m886KKQAHgyfCro1vwRpV3nqAqclsc
AhvGJXgmOeS0Mdec1PfTYaYd7UttuU8xS1l5JmEBoFfoyGsuhgVtwBq/a1xKj2pr
1hWVwV4tp+4MVNKHlnnjjY6qLYuUfE6cMvr+mfkCgYEAlmkKBTqIVRRdNqHNXRdc
pR+yiKA2DSimGSTRkjz1IB8EKfmtl6lfatPgLC6F994+sX1IaYOZO/WfI3sIpFnX
9XcwALlHvn91kpqszvzcGJ8CvSTUYp7pA3PsiDA4YuFJcJkdFrAKAclzAQb5l4yD
TjdWAfkjsucJH3sBWITJqTg=
-----END PRIVATE KEY-----
"""
SOME_OTHER_CERT = """-----BEGIN CERTIFICATE-----
MIIDETCCAfmgAwIBAgIUaLnkIGMQyPaVRHfiwOiSVr1GJNEwDQYJKoZIhvcNAQEL
BQAwFzEVMBMGA1UEAwwMU29tZW9uZSBFbHNlMCAXDTI2MTAxOTE2NTAzM1oYDzIx
MjYwOTI1MTY1MDMzWjAXMRUwEwYDVQQDDAxTb21lb25lIEVsc2UwggEiMA0GCSqG
SIb3DQEBAQUAA4IBDwAwggEKAoIBAQDEVAywti0b/hz/TfZfUB2BuACx7ev9Pv4V
rtcb17+tvwpfGDfPTTLcZKALRXcQp/WBRm7hZNy0UnUW/G/yqwh6lOADMUVWUyOg
gmuM0PI498rBeAwa1g2JbvR+lNReFRZRpq5fsLw2FetMMZSnEHmmCQrxD+HjGLoT
+LNZJtgAtzEmkmSqO5pLvbA/TdGBbvaKMYBOJNpOfh5LVSbfEpO5PZrcobuOtWHy
VgQa/+cPofv4z3lWEPLnFWzZQm6c6GWKM77f2P0uuSD23fOQS+N0//0xo/cMdGaA
LMLfUm6Yae3qtgkUsdAfeb29Vcxb6V9+FvIGmfJJ1bVFXAXnQG/FAgMBAAGjUzBR
MB0GA1UdDgQWBBTd+TM60VY0saSTv8mfplxZ16RruDAfBgNVHSMEGDAWgBTd+TM6
0VY0saSTv8mfplxZ16RruDAPBgNVHRMBAf8EBTADAQH/MA0GCSqGSIb3DQEBCwUA
A4IBAQBSa6poLI20Ifx0k4fYDf36DD0kNqnHfIDKosaMaNGywbJwzDc1YBgPJqg1
DgismCSPMsc34fe4stOJUxCgqJ/VtTVyvNO6bEjHHQBJ/vgBcNez8YOjI6QW8Sme
c/P/4ImMD2hdoofdo+woS29QuW/+KcETKEGJwZ5yTVvyIKKRkyE7D8ci+5IGjUvf
4wo6o/KZ6lXknHRadPHcQ0OIFZAj3wHzHXrHV5jFyLmT4Rc2DBeP3Tp7SRSihaXK
CQ1X87sCVdW+t8dDA2/0n+JhW5MWS+uCp6xRUbeiZ8n8MyiTM226f5hfenqVuwTX
MUxgIbmUqkla8HA76OGkb2t3sDkX
-----END CERTIFICATE-----
"""


@pytest.fixture
def server(tmp_path):
    cert, keyf = tmp_path / "leaf.pem", tmp_path / "leaf.key"
    cert.write_text(LEAF_SIGNED_BY_UNKNOWN_ISSUER)
    keyf.write_text(LEAF_KEY)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(keyf))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"CheckAuth OK")

        def log_message(self, *a):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"https://127.0.0.1:{httpd.server_address[1]}/", tmp_path
    httpd.shutdown()


def _session(cafile):
    s = requests.Session()
    s.trust_env = False                   # no proxies or env CA bundles in the way
    s.mount("https://", api.PinnedCertAdapter(cafile=str(cafile), check_hostname=False))
    return s


def test_a_pinned_certificate_verifies_without_its_issuer(server):
    url, tmp = server
    pin = tmp / "pin.pem"
    pin.write_text(LEAF_SIGNED_BY_UNKNOWN_ISSUER)
    assert _session(pin).get(url, verify=str(pin), timeout=5).text == "CheckAuth OK"


def test_pinning_a_different_certificate_is_still_refused(server):
    """The anchor is the pinned certificate - not "anything"."""
    url, tmp = server
    wrong = tmp / "wrong.pem"
    wrong.write_text(SOME_OTHER_CERT)
    with pytest.raises(requests.exceptions.SSLError):
        _session(wrong).get(url, verify=str(wrong), timeout=5)


def test_a_missing_certificate_file_is_reported_by_name(tmp_path):
    missing = tmp_path / "not-there.pem"
    client = api.InVentryAPI(base_url="https://127.0.0.1:9", api_key="k", partner_secret="s",
                             verify=str(missing), check_hostname=False,
                             limiter=type("L", (), {"acquire": lambda self: 0.0})())
    with pytest.raises(api.InVentryAPIError) as exc:
        client.check_auth()
    assert "INVENTRY_API_CA_BUNDLE" in str(exc.value)
