from __future__ import absolute_import, division, print_function

import os
import socket
import ssl

from tornado import gen
from tornado.iostream import IOStream, SSLIOStream
from tornado.log import app_log
from tornado.stack_context import NullContext
from tornado.tcpserver import TCPServer
from tornado.test.util import skipBefore35, exec_test
from tornado.testing import AsyncTestCase, ExpectLog, bind_unused_port, gen_test


class TCPServerTest(AsyncTestCase):
    @gen_test
    def test_handle_stream_coroutine_logging(self):
        # handle_stream may be a coroutine and any exception in its
        # Future will be logged.
        class TestServer(TCPServer):
            @gen.coroutine
            def handle_stream(self, stream, address):
                yield gen.moment
                stream.close()
                1 / 0

        server = client = None
        try:
            sock, port = bind_unused_port()
            with NullContext():
                server = TestServer()
                server.add_socket(sock)
            client = IOStream(socket.socket())
            with ExpectLog(app_log, "Exception in callback"):
                yield client.connect(('localhost', port))
                yield client.read_until_close()
                yield gen.moment
        finally:
            if server is not None:
                server.stop()
            if client is not None:
                client.close()

    @skipBefore35
    @gen_test
    def test_handle_stream_native_coroutine(self):
        # handle_stream may be a native coroutine.

        namespace = exec_test(globals(), locals(), """
        class TestServer(TCPServer):
            async def handle_stream(self, stream, address):
                stream.write(b'data')
                stream.close()
        """)

        sock, port = bind_unused_port()
        server = namespace['TestServer']()
        server.add_socket(sock)
        client = IOStream(socket.socket())
        yield client.connect(('localhost', port))
        result = yield client.read_until_close()
        self.assertEqual(result, b'data')
        server.stop()
        client.close()

    def test_stop_twice(self):
        sock, port = bind_unused_port()
        server = TCPServer()
        server.add_socket(sock)
        server.stop()
        server.stop()

    @gen_test
    def test_stop_in_callback(self):
        # Issue #2069: calling server.stop() in a loop callback should not
        # raise EBADF when the loop handles other server connection
        # requests in the same loop iteration

        class TestServer(TCPServer):
            @gen.coroutine
            def handle_stream(self, stream, address):
                server.stop()
                yield stream.read_until_close()

        sock, port = bind_unused_port()
        server = TestServer()
        server.add_socket(sock)
        server_addr = ('localhost', port)
        N = 40
        clients = [IOStream(socket.socket()) for i in range(N)]
        connected_clients = []

        @gen.coroutine
        def connect(c):
            try:
                yield c.connect(server_addr)
            except EnvironmentError:
                pass
            else:
                connected_clients.append(c)

        yield [connect(c) for c in clients]

        self.assertGreater(len(connected_clients), 0,
                           "all clients failed connecting")
        try:
            if len(connected_clients) == N:
                # Ideally we'd make the test deterministic, but we're testing
                # for a race condition in combination with the system's TCP stack...
                self.skipTest("at least one client should fail connecting "
                              "for the test to be meaningful")
        finally:
            for c in connected_clients:
                c.close()

        # Here tearDown() would re-raise the EBADF encountered in the IO loop

    @gen_test
    def test_custom_iostream(self):
        server_stream = []

        class MySSLIOStream(SSLIOStream):
            pass

        class MyIOStream(IOStream):
            SSLIOStream = MySSLIOStream

        class MyTCPServer(TCPServer):
            IOStream = MyIOStream

            @gen.coroutine
            def handle_stream(self, stream, address):
                server_stream.append(stream)
                stream.close()

        @gen.coroutine
        def accept_one_client(server):
            sock, port = bind_unused_port()
            server.add_socket(sock)
            client = IOStream(socket.socket())
            yield client.connect(('localhost', port))
            yield client.close()
            server.stop()

        server = MyTCPServer()
        yield accept_one_client(server)
        self.assertIsInstance(server_stream.pop(), MyIOStream)

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        ssl_ctx.load_cert_chain(
            os.path.join(os.path.dirname(__file__), 'test.crt'),
            os.path.join(os.path.dirname(__file__), 'test.key'))

        server = MyTCPServer(ssl_options=ssl_ctx)
        yield accept_one_client(server)
        self.assertIsInstance(server_stream.pop(), MySSLIOStream)
