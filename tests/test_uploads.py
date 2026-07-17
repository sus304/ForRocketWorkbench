"""Upload closure + safe extraction (design §6, §7; review 🔴B/G).

Job submission is upload-then-subprocess-execute, i.e. RCE-adjacent, so extraction must be
hardened: reject path traversal (Zip Slip), absolute paths, symlinks, and oversized/over-many
payloads. The closure must carry every input the runner actually reads -- including the MC
Wind Files Zip that runner_montecarlo unpacks from a config path -- so a remote run is
reproducible.
"""
import io
import json
import os
import tarfile
import zipfile
from pathlib import Path

import pytest

from service.uploads import pack_closure, safe_extract, UploadError


@pytest.fixture
def project(tmp_path, projects_dir):
    import shutil
    dst = tmp_path / "example"
    shutil.copytree(Path(projects_dir) / "example", dst)
    return dst


def _make_tar(members: dict) -> bytes:
    """members: {arcname: bytes}. Plain regular-file tar.gz."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


# --- safe_extract hardening ---------------------------------------------------

def test_safe_extract_normal_tar(tmp_path):
    data = _make_tar({"config_solver.json": b"{}", "sub/a.csv": b"x,y\n1,2\n"})
    dest = tmp_path / "run"
    safe_extract(data, dest)
    assert (dest / "config_solver.json").read_bytes() == b"{}"
    assert (dest / "sub" / "a.csv").exists()


def test_safe_extract_rejects_parent_traversal(tmp_path):
    data = _make_tar({"../escape.txt": b"pwned"})
    dest = tmp_path / "run"
    with pytest.raises(UploadError):
        safe_extract(data, dest)
    assert not (tmp_path / "escape.txt").exists()


def test_safe_extract_rejects_absolute_path(tmp_path):
    data = _make_tar({"/etc/pwned.txt": b"x"})
    with pytest.raises(UploadError):
        safe_extract(data, tmp_path / "run")


def test_safe_extract_rejects_symlink_member(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        ti = tarfile.TarInfo("link")
        ti.type = tarfile.SYMTYPE
        ti.linkname = "/etc/passwd"
        tar.addfile(ti)
    with pytest.raises(UploadError):
        safe_extract(buf.getvalue(), tmp_path / "run")


def test_safe_extract_enforces_file_count_limit(tmp_path):
    data = _make_tar({f"f{i}.txt": b"x" for i in range(10)})
    with pytest.raises(UploadError):
        safe_extract(data, tmp_path / "run", max_files=5)


def test_safe_extract_enforces_total_size_limit(tmp_path):
    data = _make_tar({"big.bin": b"x" * 10000})
    with pytest.raises(UploadError):
        safe_extract(data, tmp_path / "run", max_total_bytes=1000)


def test_safe_extract_nothing_written_on_rejection(tmp_path):
    data = _make_tar({"ok.txt": b"x", "../evil.txt": b"y"})
    dest = tmp_path / "run"
    with pytest.raises(UploadError):
        safe_extract(data, dest)
    assert not (tmp_path / "evil.txt").exists()


# --- closure round-trip -------------------------------------------------------

def test_pack_closure_round_trips_project(project, tmp_path):
    blob = pack_closure(project, "trajectory")
    dest = tmp_path / "run"
    safe_extract(blob, dest)
    for name in ["config_solver.json", "param_rocket.json", "thrust_mdot_p.csv", "wind.csv"]:
        assert (dest / name).exists(), name


def test_pack_closure_excludes_work_dirs(project, tmp_path):
    (project / "work_montecarlo").mkdir()
    (project / "work_montecarlo" / "junk.csv").write_text("stale")
    blob = pack_closure(project, "montecarlo")
    dest = tmp_path / "run"
    safe_extract(blob, dest)
    assert not (dest / "work_montecarlo").exists()
    assert (dest / "config_montecarlo.json").exists()


def test_pack_closure_pulls_in_external_mc_wind_zip_and_rewrites_config(project, tmp_path):
    # a wind-files zip living OUTSIDE the project, referenced by absolute path
    ext_zip = tmp_path / "external_winds.zip"
    with zipfile.ZipFile(ext_zip, "w") as z:
        z.writestr("winds/0_wind.csv", "alt,speed,dir\n0,5,90\n")
    mc = project / "config_montecarlo.json"
    cfg = json.loads(mc.read_text())
    cfg["Error Parameters"]["Wind"]["Enable"] = True
    cfg["Error Parameters"]["Wind"]["Wind Files Zip Path"] = str(ext_zip)
    mc.write_text(json.dumps(cfg))

    blob = pack_closure(project, "montecarlo")
    dest = tmp_path / "run"
    safe_extract(blob, dest)

    out_cfg = json.loads((dest / "config_montecarlo.json").read_text())
    rel = out_cfg["Error Parameters"]["Wind"]["Wind Files Zip Path"]
    assert not os.path.isabs(rel), "external zip path must be rewritten to a relative name"
    assert (dest / rel).exists(), "the external zip must be bundled into the run dir"


def test_pack_closure_missing_enabled_wind_zip_raises(project):
    mc = project / "config_montecarlo.json"
    cfg = json.loads(mc.read_text())
    cfg["Error Parameters"]["Wind"]["Enable"] = True
    cfg["Error Parameters"]["Wind"]["Wind Files Zip Path"] = "/nonexistent/winds.zip"
    mc.write_text(json.dumps(cfg))
    with pytest.raises(UploadError):
        pack_closure(project, "montecarlo")
