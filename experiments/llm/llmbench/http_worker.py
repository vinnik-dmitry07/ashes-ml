'''One bounded HTTP effect. The parent owns the wall-clock deadline.'''

import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_RESPONSE_BYTES = 524288


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def main():
    payload = json.loads(sys.stdin.buffer.read(1048576))
    key = os.environ[payload['key_env']]
    request = Request(payload['endpoint'],
                      data=bytes.fromhex(payload['request_hex']),
                      headers={'Authorization': 'Bearer ' + key,
                               'Content-Type': 'application/json'},
                      method='POST')
    try:
        response = build_opener(NoRedirect).open(
            request, timeout=payload['timeout_seconds'])
    except HTTPError as error:
        response = error
    try:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            result = {'status': 'OVERSIZE', 'http_status': response.code,
                      'response_hex': ''}
        else:
            raw = raw.replace(key.encode(), b'[REDACTED]')
            result = {'status': 'RESPONSE', 'http_status': response.code,
                      'response_hex': raw.hex()}
    finally:
        response.close()
    print(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # No exception strings, environment values, or credentials on stdout.
        print('{"status":"TRANSPORT_ERROR","http_status":0,'
              '"response_hex":""}')
