import os
import threading


class RunManifest:
    """Append-only record of completed cases in a multi-case work directory.

    A case name (the per-case solver-config file name, e.g. ``0_solver_config.json``)
    is recorded only AFTER its solver run — and any per-case post step — finishes
    successfully. This makes long runs resumable: a run interrupted partway can read
    the manifest, skip the names already recorded, and re-run only the rest. A case
    that was in flight when the run stopped is simply not in the manifest, so it is
    re-run from scratch (the natural atomic unit is one solver invocation).

    Thread-safe: ``run_multi`` calls :meth:`mark` from worker threads.
    """

    FILENAME = 'completed_cases.txt'

    def __init__(self, work_dir):
        self.path = os.path.join(work_dir, self.FILENAME)
        self._lock = threading.Lock()

    def completed(self):
        """Return the set of case names already recorded as complete."""
        if not os.path.exists(self.path):
            return set()
        with open(self.path) as f:
            return {line.strip() for line in f if line.strip()}

    def mark(self, name):
        """Durably record ``name`` as complete (fsync'd so it survives a crash)."""
        with self._lock:
            with open(self.path, 'a') as f:
                f.write(name + '\n')
                f.flush()
                os.fsync(f.fileno())
