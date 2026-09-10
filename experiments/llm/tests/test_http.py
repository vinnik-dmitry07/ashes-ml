'''Local HTTP transport exercise; no model service or real credential.'''

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ahsl.codec import canonical
from llmbench.providers import HTTPProvider


ROOT = Path(__file__).resolve().parents[1]
TEST_KEY = 'local-test-credential-no-real-account'


class LocalHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        type(self).requests.append((self.path, dict(self.headers), body))
        if self.path == '/redirect':
            self.send_response(307)
            self.send_header('Location', '/forbidden')
            self.end_headers()
            return
        if self.path == '/oversize':
            raw = b'x' * 524289
        else:
            raw = json.dumps({'authorization': self.headers['Authorization'],
                              'request': json.loads(body)}).encode()
        self.send_response(401 if self.path == '/unauthorized' else 200)
        self.end_headers()
        self.wfile.write(raw)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), LocalHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        LocalHandler.requests = []

    def provider(self, path):
        # Only this trusted transport test bypasses Route's HTTPS validation.
        # Production constructs the frozen Route before HTTPProvider.
        route = SimpleNamespace(
            endpoint='http://127.0.0.1:' + str(self.server.server_port) + path,
            timeout_seconds=2, key_env='AHSL_TEST_KEY')
        return HTTPProvider(route)

    def test_process_transport_and_exact_request_without_key_logging(self):
        with patch.dict(os.environ, {'AHSL_TEST_KEY': TEST_KEY}):
            result = self.provider('/echo').complete({'hello': 'world'})
        self.assertEqual(result['http_status'], 200)
        body = bytes.fromhex(result['response_hex'])
        self.assertNotIn(TEST_KEY.encode(), body)
        self.assertEqual(json.loads(body)['request'], {'hello': 'world'})
        request = LocalHandler.requests[0]
        self.assertEqual(request[1]['Authorization'], 'Bearer ' + TEST_KEY)
        self.assertEqual(request[2], canonical({'hello': 'world'}))

    def test_redirect_is_not_followed(self):
        with patch.dict(os.environ, {'AHSL_TEST_KEY': TEST_KEY}):
            result = self.provider('/redirect').complete({'x': 1})
        self.assertEqual(result['http_status'], 307)
        self.assertEqual(len(LocalHandler.requests), 1)

    def test_http_error_body_is_returned_as_one_paid_attempt(self):
        with patch.dict(os.environ, {'AHSL_TEST_KEY': TEST_KEY}):
            result = self.provider('/unauthorized').complete({'x': 1})
        self.assertEqual(result['http_status'], 401)
        self.assertEqual(len(LocalHandler.requests), 1)

    def test_oversize_response_is_bounded(self):
        with patch.dict(os.environ, {'AHSL_TEST_KEY': TEST_KEY}):
            result = self.provider('/oversize').complete({'x': 1})
        self.assertEqual(result['status'], 'OVERSIZE')
        self.assertEqual(result['response_hex'], '')

    def test_parent_timeout_does_not_retry_or_expose_exception(self):
        timeout = subprocess.TimeoutExpired('worker', 2, output=b'secret')
        with patch.dict(os.environ, {'AHSL_TEST_KEY': TEST_KEY}):
            with patch('llmbench.providers.subprocess.run',
                       side_effect=timeout) as runner:
                result = self.provider('/echo').complete({'x': 1})
        self.assertEqual(result['status'], 'TIMEOUT')
        self.assertEqual(result['response_hex'], '')
        self.assertEqual(runner.call_count, 1)

    def test_worker_error_does_not_echo_secret(self):
        worker = ROOT / 'llmbench/http_worker.py'
        result = subprocess.run(
            [sys.executable, str(worker)], input=b'not json',
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(json.loads(result.stdout)['status'],
                         'TRANSPORT_ERROR')
        self.assertEqual(result.stderr, b'')


if __name__ == '__main__':
    unittest.main()
