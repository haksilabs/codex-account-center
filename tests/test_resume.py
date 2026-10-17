from pathlib import Path
import runpy
import socket
import tempfile
import unittest
from unittest.mock import patch


MOD = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'src/codex-acc'))
RESUME = MOD['resume_codex_thread']
IPC = MOD['_try_codex_ipc_start_turn']
GLOBALS = RESUME.__globals__
THREAD = '00000000-0000-4000-8000-000000000001'


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class DesktopResumeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / 'ipc').mkdir()
        (root / 'ipc/ipc.sock').touch()
        # Socket I/O is mocked below; only the existence check needs a fixture.
        patcher = patch.dict(GLOBALS, CODEX_DIR=root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def invoke(self, replies, open_errors=None):
        clock = Clock()
        calls = []
        opens = []
        spawned = []
        reply_iter = iter(replies)
        last_reply = replies[-1]

        def ipc(thread, text):
            calls.append((thread, text))
            return next(reply_iter, last_reply)

        def open_thread(thread):
            opens.append(thread)
            if open_errors:
                raise OSError('desktop not available')

        with patch.dict(GLOBALS, {
            'get_auto_config': lambda: {'resume_prompt': 'continue saved work'},
            'is_chatgpt_app_running': lambda: True,
            '_try_codex_ipc_start_turn': ipc,
            '_open_codex_thread_in_desktop': open_thread,
        }), patch.object(GLOBALS['time'], 'monotonic', clock.monotonic), \
             patch.object(GLOBALS['time'], 'sleep', clock.sleep), \
             patch.object(GLOBALS['subprocess'], 'Popen', lambda args, **kw: spawned.append(args)):
            result = RESUME(THREAD, wait_for_app_seconds=2)
        self.assertTrue(all(cmd[0] == 'notify-send' for cmd in spawned), spawned)
        return result, calls, opens

    def test_unloaded_thread_is_opened_before_desktop_continuation(self):
        result, calls, opens = self.invoke([
            (False, 'ipc_owner_bulunamadi'), (True, 'ipc_desktop')
        ])
        self.assertTrue(result['ok'])
        self.assertEqual(result['method'], 'ipc_desktop')
        self.assertEqual(opens, [THREAD])
        self.assertEqual(len(calls), 2)

    def test_timeout_does_not_launch_competing_cli_writer(self):
        result, calls, opens = self.invoke([(False, 'ipc_owner_bulunamadi')])
        self.assertFalse(result['ok'])
        self.assertEqual(result['method'], 'desktop_pending')
        self.assertEqual(opens, [THREAD])
        self.assertGreater(len(calls), 2)

    def test_lost_acknowledgement_is_not_retried(self):
        result, calls, opens = self.invoke([(False, 'ipc_gonderim_belirsiz')])
        self.assertFalse(result['ok'])
        self.assertEqual(result['method'], 'desktop_unconfirmed')
        self.assertEqual(len(calls), 1)
        self.assertEqual(opens, [])

    def test_rejection_is_not_reported_as_success(self):
        result, calls, opens = self.invoke([(False, 'ipc_hata:writer-conflict')])
        self.assertFalse(result['ok'])
        self.assertEqual(result['method'], 'desktop_rejected')
        self.assertEqual(len(calls), 1)
        self.assertEqual(opens, [])

    def test_socket_closes_after_read_only_probe(self):
        sent = []
        sockets = []

        class FakeSocket:
            def __init__(self, *args):
                self.closed = False
                sockets.append(self)
            def connect(self, path):
                pass
            def close(self):
                self.closed = True

        def send(sock, message):
            sent.append(message)

        def recv(sock, timeout):
            request = sent[-1]
            return {'type': 'response', 'requestId': request['requestId'],
                    'resultType': 'success', 'handledByClientId': 'desktop',
                    'result': {'clientId': 'test'}}

        with patch.object(GLOBALS['socket'], 'socket', FakeSocket), \
             patch.dict(GLOBALS, {'_ipc_send_frame': send, '_ipc_recv_frame': recv}):
            result = IPC(THREAD, '', probe_only=True)
        self.assertTrue(result[0])
        self.assertEqual([r['method'] for r in sent], ['initialize', 'thread-owner-discovery'])
        self.assertTrue(all(s.closed for s in sockets))

    def test_connection_loss_after_send_has_uncertain_delivery(self):
        sent = []

        class FakeSocket:
            def __init__(self, *args):
                pass
            def connect(self, path):
                pass
            def close(self):
                pass

        def send(sock, message):
            sent.append(message)

        def recv(sock, timeout):
            request = sent[-1]
            if request['method'] == 'thread-follower-start-turn':
                raise socket.timeout('lost acknowledgement')
            return {'type': 'response', 'requestId': request['requestId'],
                    'resultType': 'success', 'handledByClientId': 'desktop',
                    'result': {'clientId': 'test'}}

        with patch.object(GLOBALS['socket'], 'socket', FakeSocket), \
             patch.dict(GLOBALS, {'_ipc_send_frame': send, '_ipc_recv_frame': recv}):
            result = IPC(THREAD, 'continue saved work')
        self.assertEqual(result, (False, 'ipc_gonderim_belirsiz'))
        self.assertEqual(sum(r['method'] == 'thread-follower-start-turn' for r in sent), 1)
        turn_request = next(r for r in sent if r['method'] == 'thread-follower-start-turn')
        content = turn_request['params']['turnStart']['request']['input']
        self.assertEqual(content, [{'type': 'text', 'text': 'continue saved work', 'text_elements': []}])


if __name__ == '__main__':
    unittest.main(verbosity=2)
