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

from datetime import timedelta

from tornado import gen, locks
from tornado.gen import TimeoutError
from tornado.testing import gen_test, AsyncTestCase
from tornado.test.util import unittest


class ConditionTest(AsyncTestCase):
    def setUp(self):
        super(ConditionTest, self).setUp()
        self.history = []

    def record_done(self, future, key):
        """Record the resolution of a Future returned by Condition.wait."""
        def callback(_):
            if not future.result():
                # wait() resolved to False, meaning it timed out.
                self.history.append('timeout')
            else:
                self.history.append(key)
        future.add_done_callback(callback)

    def test_str(self):
        c = locks.Condition()
        self.assertIn('Condition', str(c))
        self.assertNotIn('waiters', str(c))
        c.wait()
        self.assertIn('waiters', str(c))

    @gen_test
    def test_notify(self):
        c = locks.Condition()
        self.io_loop.call_later(0.01, c.notify)
        yield c.wait()

    def test_notify_1(self):
        c = locks.Condition()
        self.record_done(c.wait(), 'wait1')
        self.record_done(c.wait(), 'wait2')
        c.notify(1)
        self.history.append('notify1')
        c.notify(1)
        self.history.append('notify2')
        self.assertEqual(['wait1', 'notify1', 'wait2', 'notify2'],
                         self.history)

    def test_notify_n(self):
        c = locks.Condition()
        for i in range(6):
            self.record_done(c.wait(), i)

        c.notify(3)

        # Callbacks execute in the order they were registered.
        self.assertEqual(list(range(3)), self.history)
        c.notify(1)
        self.assertEqual(list(range(4)), self.history)
        c.notify(2)
        self.assertEqual(list(range(6)), self.history)

    def test_notify_all(self):
        c = locks.Condition()
        for i in range(4):
            self.record_done(c.wait(), i)

        c.notify_all()
        self.history.append('notify_all')

        # Callbacks execute in the order they were registered.
        self.assertEqual(
            list(range(4)) + ['notify_all'],
            self.history)

    @gen_test
    def test_wait_timeout(self):
        c = locks.Condition()
        self.assertFalse((yield c.wait(timedelta(seconds=0.01))))

    @gen_test
    def test_wait_timeout_preempted(self):
        c = locks.Condition()

        # This fires before the wait times out.
        self.io_loop.call_later(0.01, c.notify)
        yield c.wait(timedelta(seconds=1))

    @gen_test
    def test_notify_n_with_timeout(self):
        # Register callbacks 0, 1, 2, and 3. Callback 1 has a timeout.
        # Wait for that timeout to expire, then do notify(2) and make
        # sure everyone runs. Verifies that a timed-out callback does
        # not count against the 'n' argument to notify().
        c = locks.Condition()
        self.record_done(c.wait(), 0)
        self.record_done(c.wait(timedelta(seconds=0.01)), 1)
        self.record_done(c.wait(), 2)
        self.record_done(c.wait(), 3)

        # Wait for callback 1 to time out.
        yield gen.sleep(0.02)
        self.assertEqual(['timeout'], self.history)

        c.notify(2)
        yield gen.sleep(0.01)
        self.assertEqual(['timeout', 0, 2], self.history)
        self.assertEqual(['timeout', 0, 2], self.history)
        c.notify()
        self.assertEqual(['timeout', 0, 2, 3], self.history)

    @gen_test
    def test_notify_all_with_timeout(self):
        c = locks.Condition()
        self.record_done(c.wait(), 0)
        self.record_done(c.wait(timedelta(seconds=0.01)), 1)
        self.record_done(c.wait(), 2)

        # Wait for callback 1 to time out.
        yield gen.sleep(0.02)
        self.assertEqual(['timeout'], self.history)

        c.notify_all()
        self.assertEqual(['timeout', 0, 2], self.history)

    @gen_test
    def test_nested_notify(self):
        # Ensure no notifications lost, even if notify() is reentered by a
        # waiter calling notify().
        c = locks.Condition()

        # Three waiters.
        futures = [c.wait() for _ in range(3)]

        # First and second futures resolved. Second future reenters notify(),
        # resolving third future.
        futures[1].add_done_callback(lambda _: c.notify())
        c.notify(2)
        self.assertTrue(all(f.done() for f in futures))

    @gen_test
    def test_garbage_collection(self):
        # Test that timed-out waiters are occasionally cleaned from the queue.
        c = locks.Condition()
        for _ in range(101):
            c.wait(timedelta(seconds=0.01))

        future = c.wait()
        self.assertEqual(102, len(c._waiters))

        # Let first 101 waiters time out, triggering a collection.
        yield gen.sleep(0.02)
        self.assertEqual(1, len(c._waiters))

        # Final waiter is still active.
        self.assertFalse(future.done())
        c.notify()
        self.assertTrue(future.done())


class TestEvent(AsyncTestCase):
    def test_str(self):
        event = locks.Event()
        self.assertTrue('clear' in str(event))
        self.assertFalse('set' in str(event))
        event.set()
        self.assertFalse('clear' in str(event))
        self.assertTrue('set' in str(event))

    def test_event(self):
        e = locks.Event()
        future_0 = e.wait()
        e.set()
        future_1 = e.wait()
        e.clear()
        future_2 = e.wait()

        self.assertTrue(future_0.done())
        self.assertTrue(future_1.done())
        self.assertFalse(future_2.done())

    @gen_test
    def test_event_timeout(self):
        e = locks.Event()
        with self.assertRaises(TimeoutError):
            yield e.wait(timedelta(seconds=0.01))

        # After a timed-out waiter, normal operation works.
        self.io_loop.add_timeout(timedelta(seconds=0.01), e.set)
        yield e.wait(timedelta(seconds=1))

    def test_event_set_multiple(self):
        e = locks.Event()
        e.set()
        e.set()
        self.assertTrue(e.is_set())

    def test_event_wait_clear(self):
        e = locks.Event()
        f0 = e.wait()
        e.clear()
        f1 = e.wait()
        e.set()
        self.assertTrue(f0.done())
        self.assertTrue(f1.done())


if __name__ == '__main__':
    unittest.main()
