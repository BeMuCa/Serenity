"""
============================================================
Author:  Berk
Created: 2026-07-19
Purpose: Unit-test the pure, thread-safe LlmQueue (FIFO, dedup, pause/resume/
         prioritize, global pause, atomic next_runnable, snapshot, is_busy).
Role:    Headless core for the LLM job queue (Infra A). Guards folds 11.1/11.5/11.11.

Test classes:
- TestQueueOps — ordering, dedup, pause/resume/prioritize, global pause, snapshot
- TestConcurrency — 11.1 two-thread hammer; 11.5 wait wakes on submit
============================================================
"""
import threading
import time

from serenity.core.llm_queue import LlmQueue, LlmJob, JobState


def _job(label):
    return LlmJob(label=label, run=lambda llm: label)


class TestQueueOps:
    def test_fifo_next_runnable_transitions_running(self):
        q = LlmQueue()
        a, b = _job("a"), _job("b")
        q.submit(a); q.submit(b)
        got = q.next_runnable()
        assert got is a and got.state == JobState.RUNNING
        # second pick returns b (a is still RUNNING, not re-picked)
        assert q.next_runnable() is b

    def test_dedup_identical_label_pending_or_running(self):
        q = LlmQueue()
        assert q.submit(_job("dig")) is True
        assert q.submit(_job("dig")) is False          # identical label still PENDING
        run = q.next_runnable()                          # dig -> RUNNING
        assert q.submit(_job("dig")) is False          # identical label now RUNNING
        assert q.submit(_job("other")) is True

    def test_pause_skips_then_resume_restores(self):
        q = LlmQueue()
        a, b = _job("a"), _job("b")
        q.submit(a); q.submit(b)
        assert q.pause(a.id) is True
        assert q.next_runnable() is b                    # a paused -> skipped
        assert q.resume(a.id) is True
        assert q.next_runnable() is a

    def test_pause_is_noop_off_pending(self):
        q = LlmQueue()
        a = _job("a"); q.submit(a); q.next_runnable()    # a RUNNING
        assert q.pause(a.id) is False                    # 11.11: no-op off PENDING
        assert q.resume(a.id) is False                   # a is not PAUSED

    def test_prioritize_moves_to_front(self):
        q = LlmQueue()
        a, b, c = _job("a"), _job("b"), _job("c")
        for j in (a, b, c): q.submit(j)
        assert q.prioritize(c.id) is True
        assert q.next_runnable() is c

    def test_global_pause_blocks_and_resume_unblocks(self):
        q = LlmQueue()
        a = _job("a"); q.submit(a)
        q.pause_all()
        assert q.next_runnable() is None
        assert q.is_busy() is False                      # nothing RUNNING, paused -> not busy
        q.resume_all()
        assert q.next_runnable() is a

    def test_snapshot_shape_and_isolation(self):
        q = LlmQueue()
        a, b = _job("a"), _job("b")
        q.submit(a); q.submit(b)
        q.next_runnable()                                 # a RUNNING
        running, pending = q.snapshot()
        assert running.label == "a" and running.state == JobState.RUNNING
        assert [p.label for p in pending] == ["b"]
        pending.clear()                                   # mutating the copy must not affect the queue
        assert q.snapshot()[1][0].label == "b"

    def test_is_busy_true_while_running(self):
        q = LlmQueue()
        a = _job("a"); q.submit(a)
        assert q.is_busy() is True                        # runnable PENDING
        q.next_runnable()
        assert q.is_busy() is True                        # RUNNING
        q.mark_done(a)
        assert q.is_busy() is False


class TestConcurrency:
    def test_next_runnable_wakes_on_submit(self):        # fold 11.5
        q = LlmQueue()
        result = {}
        def waiter():
            result["job"] = q.next_runnable(wait_timeout=2.0)
        t = threading.Thread(target=waiter); t.start()
        time.sleep(0.05)                                  # ensure the waiter is parked in wait()
        q.submit(_job("late"))
        t.join(timeout=2.0)
        assert result["job"] is not None and result["job"].label == "late"

    def test_hammer_no_lost_or_duplicate_jobs(self):     # fold 11.1
        q = LlmQueue()
        N = 200
        processed = []
        stop = threading.Event()

        def worker():
            while not stop.is_set() or q.snapshot()[0] or q.snapshot()[1]:
                job = q.next_runnable(wait_timeout=0.02)
                if job is None:
                    continue
                processed.append(job.id)
                q.mark_done(job)

        def submitter():
            for i in range(N):
                j = LlmJob(label=f"j{i}", run=lambda llm: "")
                q.submit(j)
                if i % 3 == 0:
                    q.prioritize(j.id)
                if i % 5 == 0:
                    q.pause(j.id); q.resume(j.id)
            stop.set()

        wt = threading.Thread(target=worker); st = threading.Thread(target=submitter)
        wt.start(); st.start(); st.join(); wt.join(timeout=5.0)
        assert len(processed) == N                        # every job ran
        assert len(set(processed)) == N                   # none ran twice

    def test_paused_worker_poll_waits_not_spins(self):   # busy-spin regression (11.5)
        q = LlmQueue()
        q.submit(_job("a"))
        q.pause_all()
        # a worker-style timed poll must BLOCK ~the timeout when globally paused,
        # not return None instantly (which would busy-spin the drain loop)
        t0 = time.monotonic()
        assert q.next_runnable(wait_timeout=0.2) is None
        assert time.monotonic() - t0 >= 0.15
        # resume_all wakes a paused waiter promptly
        def resumer():
            time.sleep(0.05); q.resume_all()
        threading.Thread(target=resumer).start()
        t0 = time.monotonic()
        got = q.next_runnable(wait_timeout=2.0)
        assert got is not None and got.label == "a"
        assert time.monotonic() - t0 < 1.0
