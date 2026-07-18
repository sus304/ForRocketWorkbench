"""Guard for the example-copy test fixture (tests/_project.py).

copy_example copies projects/example into a temp dir. The example ships only tracked input
files, but a local, gitignored work_* output dir (left by a prior manual run in projects/
example) must NOT be carried into the copy: make_unique_work_dir would then find work_trajectory
already present and create work_trajectory_01, breaking the trajectory / self-contained work-dir
tests with a spurious "two work dirs" failure. copy_example must isolate the copy from that
local pollution.
"""
from tests._project import copy_example


def test_copy_example_excludes_stray_work_dirs(tmp_path):
    src = tmp_path / "projects"
    ex = src / "example"
    ex.mkdir(parents=True)
    (ex / "config_solver.json").write_text("{}")
    # Stray, gitignored outputs from a prior manual run in projects/example.
    (ex / "work_trajectory").mkdir()
    (ex / "work_trajectory" / "SAMPLE_stage1_flight_log.csv").write_text("t\n0\n")
    (ex / "work_montecarlo_03").mkdir()

    dst = copy_example(src, tmp_path / "copy")

    assert (dst / "config_solver.json").exists(), "tracked inputs must still be copied"
    assert not (dst / "work_trajectory").exists(), "stray work dir must not be carried over"
    assert not (dst / "work_montecarlo_03").exists()
