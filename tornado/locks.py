# Copyright 2015 The Tornado Authors
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from __future__ import absolute_import, division, print_function, with_statement

__all__ = ['Condition']

import collections

from tornado import concurrent, gen, ioloop
from tornado.concurrent import Future


class Condition(object):
    """A condition allows one or more coroutines to wait until notified.

    Like a standard `threading.Condition`, but does not need an underlying lock
    that is acquired and released.
    """

    def __init__(self):
        self.io_loop = ioloop.IOLoop.current()
        self._waiters = collections.deque()  # Futures.
        self._timeouts = 0

    def __str__(self):
        result = '<%s' % (self.__class__.__name__, )
        if self._waiters:
            result += ' waiters[%s]' % len(self._waiters)
        return result + '>'

    def wait(self, timeout=None):
        """Wait for `.notify`.

        Returns a `.Future` that resolves ``True`` if the condition is notified,
        or ``False`` after a timeout.
        """
        waiter = Future()
        self._waiters.append(waiter)
        if timeout:
            def on_timeout():
                waiter.set_result(False)
                self._garbage_collect()
            self.io_loop.add_timeout(timeout, on_timeout)
        return waiter

    def notify(self, n=1):
        """Wake ``n`` waiters."""
        waiters = []  # Waiters we plan to run right now.
        while n and self._waiters:
            waiter = self._waiters.popleft()
            if not waiter.done():  # Might have timed out.
                n -= 1
                waiters.append(waiter)

        for waiter in waiters:
            waiter.set_result(True)

    def notify_all(self):
        """Wake all waiters."""
        self.notify(len(self._waiters))

    def _garbage_collect(self):
        # Occasionally clear timed-out waiters, if many coroutines wait with a
        # timeout but notify is called rarely.
        self._timeouts += 1
        if self._timeouts > 100:
            self._timeouts = 0
            self._waiters = collections.deque(
                w for w in self._waiters if not w.done())
