import contextlib
import io
import os
import socket
import ssl
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from finmind_diagnostic import run_diagnostic, _classify, _sanitize
class Budget:
 def __init__(self,**kw): pass
 def consume(self): pass
class Response:
 status_code=200
 def raise_for_status(self): pass
 def json(self): return {'status':200,'data':[]}
class Session:
 created=0
 def __init__(self): self.headers={}; self.calls=0; Session.created+=1
 def get(self,*a,**kw): self.calls+=1; self.kw=kw; return Response()
 def close(self): pass
class Raw:
 _closed=False
 def close(self): self._closed=True
class Secure:
 def getpeercert(self): return {'ok':True}
 def version(self): return 'TLSv1.3'
 def __enter__(self): return self
 def __exit__(self,*a): pass
class Context:
 def wrap_socket(self,*a,**kw): return Secure()
class DiagnosticTests(unittest.TestCase):
 def test_one_request_no_secrets_proxy_values_or_headers_in_output(self):
  output=io.StringIO()
  with patch.dict(os.environ,{'FINMIND_TOKEN':'secret-test-token','HTTPS_PROXY':'https://private-proxy.invalid'}):
   with contextlib.redirect_stdout(output):
    result=run_diagnostic('2330',session_factory=Session,budget_factory=Budget,
      dns_lookup=lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))],
      tcp_connect=lambda *a,**k:Raw(),ssl_context_factory=Context)
  text=output.getvalue()
  self.assertTrue(result['success']); self.assertEqual(result['api_requests'],1)
  self.assertEqual(Session.created,1); self.assertNotIn('secret-test-token',text)
  self.assertNotIn('private-proxy.invalid',text); self.assertIn('HTTPS_PROXY=True',text)
  self.assertIn('[OK] FinMind connection successful',text)
 def test_dns_error_is_classified_and_sanitized(self):
  exc=socket.gaierror(socket.EAI_NONAME,'name resolution failed for token=secret')
  self.assertEqual(_classify(exc)[1],'DNS/name resolution error')
  self.assertNotIn('secret',_sanitize(exc,'secret'))
 def test_invalid_stock_rejected_before_any_request(self):
  with self.assertRaises(ValueError): run_diagnostic('../',session_factory=Session,budget_factory=Budget)
if __name__=='__main__': unittest.main()
