"""Offline configuration/API tests; no Bluetooth or real coordinator commands."""

import asyncio
from contextlib import redirect_stderr
import http.client
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from haptic_demo import make_server, parse_args, run
from whoop_haptic_link import WhoopHapticLink


class ConfigurationTests(unittest.TestCase):
    def test_no_private_identity_defaults_and_cli_overrides_environment(self):
        with patch.dict(os.environ, {}, clear=True), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args([])
            args = parse_args(['--whoop-source', 'test-device', '--whoop-serial', 'TEST-SERIAL'])
            self.assertIsNone(args.heartcast_source)
            self.assertEqual(args.port, 8767)
        env = dict(WHOOP_SOURCE_ID='env-device', WHOOP_SERIAL='ENV-SERIAL',
                   HEARTCAST_SOURCE_ID='env-heart')
        with patch.dict(os.environ, env, clear=True):
            args = parse_args(['--whoop-source', 'cli-device', '--whoop-serial', 'CLI-SERIAL'])
        self.assertEqual((args.whoop_source, args.whoop_serial, args.heartcast_source),
                         ('cli-device', 'CLI-SERIAL', 'env-heart'))
        for source, serial in [(None, None), ('', 'TEST-SERIAL'), ('device', ' '), (True, 'serial')]:
            with self.assertRaises(ValueError):
                WhoopHapticLink(source=source, serial=serial)

    @unittest.skipUnless(shutil.which('zsh'), 'Mac launcher requires zsh')
    def test_launcher_resolves_its_own_directory_and_configuration_priority(self):
        source = Path(__file__).resolve().parents[1] / 'start_haptic_demo.command'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'checkout with spaces'
            root.mkdir()
            launcher = root / source.name
            launcher.write_bytes(source.read_bytes())
            python = root / '.venv/bin/python'
            python.parent.mkdir(parents=True)
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            python.chmod(0o700)
            (root / '.env.local').write_text(
                "WHOOP_SOURCE_ID='file device'\nWHOOP_SERIAL='FILE-SERIAL'\n"
                "HEARTCAST_SOURCE_ID='file heart'\n")
            env = {'PATH': os.defpath, 'WHOOP_SOURCE_ID': 'env-device'}
            completed = subprocess.run([shutil.which('zsh'), str(launcher),
                                        '--whoop-serial', 'CLI-SERIAL'],
                                       cwd=temporary, env=env, text=True, capture_output=True, check=True)
            argv = completed.stdout.splitlines()
            self.assertEqual(argv[:2], ['-u', 'haptic_demo.py'])
            with patch.dict(os.environ, {}, clear=True):
                args = parse_args(argv[2:])
            self.assertEqual((args.whoop_source, args.whoop_serial, args.heartcast_source),
                             ('env-device', 'CLI-SERIAL', 'file heart'))


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_occupied_port_cannot_reset_existing_round_or_replace_token(self):
        with patch('haptic_demo.make_server', side_effect=OSError('address in use')), \
                patch('haptic_demo.request_motion_reset') as reset, \
                patch('haptic_demo.os.open') as write_token:
            with self.assertRaises(OSError):
                await run(8767, whoop_source='test-device', whoop_serial='TEST-SERIAL')
        reset.assert_not_called()
        write_token.assert_not_called()


class ApiTests(unittest.TestCase):
    def test_exported_dashboard_and_bridge_get_api_use_local_sources(self):
        loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=loop.run_forever)
        loop_thread.start()
        heart = SimpleNamespace(current_bpm=lambda _age: 91)
        demo = SimpleNamespace(apple_heart_rate=heart, snapshot=lambda: {'phase': 'idle'})
        server = make_server(demo, loop, 'test-token', 0)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.start()
        try:
            def get(path, host='127.0.0.1:0'):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
                try:
                    connection.request('GET', path, headers={'Host': host})
                    response = connection.getresponse()
                    return response.status, response.read(), response.getheader('Content-Type')
                finally:
                    connection.close()

            with patch('haptic_demo.read_whoop_bpm', return_value=72):
                status, body, _ = get('/api/heart-rate')
                self.assertEqual((status, json.loads(body)),
                                 (200, {'apple_watch_bpm': 91, 'bpm': 72}))
                demo.apple_heart_rate = None
                self.assertIsNone(json.loads(get('/api/heart-rate')[1])['apple_watch_bpm'])
            self.assertEqual(json.loads(get('/api/state')[1]), {'phase': 'idle'})
            self.assertEqual(json.loads(get('/api/session')[1]), {'token': 'test-token'})
            for path in ('/', '/app.js', '/style.css'):
                status, body, _ = get(path)
                self.assertEqual(status, 200)
                self.assertTrue(body)
            self.assertEqual(get('/api/session', host='remote.example')[0], 403)
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join()
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join()
            loop.close()
