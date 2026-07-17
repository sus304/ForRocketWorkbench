"""Decoupled notification (design §8; user: no corporate Slack key).

Notification is optional and service-agnostic: if WB_NOTIFY_URL is unset there is simply no
push (status is still visible via the API/UI). When set, it posts to a generic webhook;
ntfy (keyless, self-hostable) is the recommended target, and Slack/Discord/custom endpoints
share the same entry. Delivery failures never propagate into the worker.
"""
import sys

import pytest

from service.notify import Notifier
from service.store import JobStore, COMPLETED, FAILED
from service.worker import Worker


class _Recorder:
    def __init__(self, fail=False):
        self.calls = []
        self._fail = fail

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self._fail:
            raise RuntimeError("network down")
        return None


def test_no_url_is_noop():
    rec = _Recorder()
    n = Notifier(url="", post=rec)
    assert n.notify("t", "m") is False
    assert rec.calls == []


def test_ntfy_posts_body_with_title_header():
    rec = _Recorder()
    n = Notifier(url="https://ntfy.sh/my-topic", post=rec)
    assert n.notify("MC done", "landing dispersion ready") is True
    url, kw = rec.calls[0]
    assert url == "https://ntfy.sh/my-topic"
    assert kw["headers"]["Title"] == "MC done"
    assert b"landing dispersion ready" in kw["data"]


def test_slack_posts_json_text():
    rec = _Recorder()
    n = Notifier(url="https://hooks.slack.com/services/XXX", post=rec)
    n.notify("MC done", "ok")
    _, kw = rec.calls[0]
    assert "text" in kw["json"]


def test_generic_posts_json_title_message():
    rec = _Recorder()
    n = Notifier(url="https://example.com/webhook", post=rec)
    n.notify("t", "m")
    _, kw = rec.calls[0]
    assert kw["json"]["title"] == "t"
    assert kw["json"]["message"] == "m"


def test_delivery_failure_is_swallowed_and_retried():
    rec = _Recorder(fail=True)
    n = Notifier(url="https://ntfy.sh/x", post=rec, retries=2)
    assert n.notify("t", "m") is False       # never raises
    assert len(rec.calls) == 3               # initial + 2 retries


# --- worker fires events on terminal states ----------------------------------

_STUB_RUNNER = ('import sys,os\nargs=sys.argv[1:]\nwd=None\n'
                'for i,a in enumerate(args):\n'
                '    if a in ("-w","--work-dir"): wd=args[i+1]\n'
                'code=int(open(os.path.join(os.getcwd(),"_stub_exit")).read()) '
                'if os.path.exists(os.path.join(os.getcwd(),"_stub_exit")) else 0\n'
                'if code==0 and wd: open(os.path.join(wd,"ran.txt"),"w").write("ok")\n'
                'sys.exit(code)\n')
_STUB_POST = 'import sys,os\nopen(os.path.join(sys.argv[-1],"post_done.txt"),"w").write("ok")\n'


@pytest.fixture
def store(tmp_path):
    s = JobStore(tmp_path / "jobs.db")
    yield s
    s.close()


def _worker(tmp_path, store, events):
    (tmp_path / "r.py").write_text(_STUB_RUNNER)
    (tmp_path / "p.py").write_text(_STUB_POST)
    return Worker(store, tmp_path / "data", python=sys.executable,
                  runner_py=str(tmp_path / "r.py"), post_py=str(tmp_path / "p.py"),
                  poll=0.05, on_event=lambda jid, status, summary="": events.append((jid, status)))


def test_worker_emits_completed_event(tmp_path, store):
    events = []
    w = _worker(tmp_path, store, events)
    jid = store.enqueue(mode="trajectory")
    w.run_dir_for(jid).mkdir(parents=True)
    w.run_one(store.claim_next())
    assert (jid, COMPLETED) in events


def test_worker_emits_failed_event(tmp_path, store):
    events = []
    w = _worker(tmp_path, store, events)
    jid = store.enqueue(mode="area")
    rd = w.run_dir_for(jid)
    rd.mkdir(parents=True)
    (rd / "_stub_exit").write_text("2")
    w.run_one(store.claim_next())
    assert (jid, FAILED) in events
