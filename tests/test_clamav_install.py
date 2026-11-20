"""Exercise rootless installation with empty APT indexes and real local .deb files."""

import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APT_GET = shutil.which("apt-get")
DPKG_DEB = shutil.which("dpkg-deb")
SCAN_PACKAGES = shutil.which("dpkg-scanpackages")
pytestmark = pytest.mark.skipif(
    not all((APT_GET, DPKG_DEB, SCAN_PACKAGES)), reason="Needs Debian/Ubuntu package tools"
)


def package(repository, name, files, dependencies=""):
    source = repository / f"source-{name}"
    (source / "DEBIAN").mkdir(parents=True)
    control = (
        f"Package: {name}\nVersion: 1.0\nArchitecture: all\n"
        "Maintainer: Test <test@example.org>\n"
    )
    if dependencies:
        control += f"Depends: {dependencies}\n"
    (source / "DEBIAN/control").write_text(control + "Description: Isolated installer fixture\n")
    for relative, content in files.items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        if relative.startswith("usr/bin/"):
            target.chmod(0o755)
    subprocess.run(
        [DPKG_DEB, "--build", "--root-owner-group", str(source), str(repository / f"{name}.deb")],
        check=True, capture_output=True,
    )


@pytest.mark.parametrize(
    "engine_library,compression_library,architecture,certificates",
    [
        ("libclamav9", "libmspack0", "x86_64-linux-gnu", False),
        ("libclamav12", "libmspack0t64", "aarch64-linux-gnu", True),
    ],
)
def test_install_resolves_host_dependencies_without_system_indexes(
    tmp_path, engine_library, compression_library, architecture, certificates,
):
    project = tmp_path / "project"
    (project / "deploy").mkdir(parents=True)
    for name in ("install-local-clamav.sh", "clamav-local"):
        shutil.copy2(ROOT / "deploy" / name, project / "deploy" / name)
    repository = tmp_path / "repository"
    repository.mkdir()
    library_dir = f"usr/lib/{architecture}"
    engine_files = {f"{library_dir}/engine-fixture": "Engine dependency"}
    if certificates:
        engine_files["etc/clamav/certs/fixture.pem"] = "Certificate fixture"
    package(repository, compression_library, {f"{library_dir}/compression-fixture": "Dependency"})
    package(repository, engine_library, engine_files, compression_library)
    package(repository, "clamav", {"usr/bin/clamscan": "#!/bin/sh\nexit 0\n"}, engine_library)
    # An older updater rejects the newer certificate option. Also verify the
    # wrapper exposes dependencies extracted for either architecture.
    updater = f"""#!{sys.executable}
import os
import sys
from pathlib import Path
configuration = Path(sys.argv[1].split('=', 1)[1]).read_text()
assert ('CVDCertsDirectory ' in configuration) is {certificates!r}
directories = os.environ['LD_LIBRARY_PATH'].split(os.pathsep)
assert any((Path(item) / 'engine-fixture').is_file() for item in directories)
assert any((Path(item) / 'compression-fixture').is_file() for item in directories)
"""
    package(repository, "clamav-freshclam", {"usr/bin/freshclam": updater}, engine_library)
    packages = subprocess.run(
        [SCAN_PACKAGES, ".", "/dev/null"], cwd=repository,
        check=True, capture_output=True, text=True,
    )
    (repository / "Packages").write_text(packages.stdout)
    (repository / "sources.list").write_text(f"deb [trusted=yes] copy:{repository} ./\n")
    (repository / "status").touch()

    # Redirect only repository inputs to the local fixture. The installer still
    # creates its own empty indexes, locks and archive cache and runs real APT.
    binaries = tmp_path / "bin"
    binaries.mkdir()
    apt_wrapper = binaries / "apt-get"
    apt_wrapper.write_text(f"""#!{sys.executable}
import os
import sys
from pathlib import Path
config = Path(os.environ['APT_CONFIG'])
with config.open('a') as output:
    output.write('Dir::Etc::sourcelist "{repository / 'sources.list'}";\\n')
    output.write('Dir::Etc::sourceparts "-";\\n')
    output.write('Dir::State::status "{repository / 'status'}";\\n')
os.execv({APT_GET!r}, [{APT_GET!r}, *sys.argv[1:]])
""")
    apt_wrapper.chmod(0o755)
    environment = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"])
    result = subprocess.run(
        ["sh", str(project / "deploy/install-local-clamav.sh")],
        env=environment, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    scanner_root = project / ".local-tools/clamav"
    assert (scanner_root / "runtime" / library_dir / "engine-fixture").is_file()
    assert (scanner_root / "runtime" / library_dir / "compression-fixture").is_file()
    assert (scanner_root / "signatures/.updated").is_file()
    assert not list((scanner_root / "packages").iterdir())
    assert (repository / "status").read_text() == ""


@pytest.mark.parametrize("stamp", [None, "invalid", "expired"])
def test_local_scanner_rejects_unavailable_or_stale_updates(tmp_path, stamp):
    (tmp_path / "deploy").mkdir()
    scanner = tmp_path / "deploy/clamav-local"
    shutil.copy2(ROOT / "deploy/clamav-local", scanner)
    if stamp is not None:
        signatures = tmp_path / ".local-tools/clamav/signatures"
        signatures.mkdir(parents=True)
        value = datetime.now(UTC) - timedelta(hours=73) if stamp == "expired" else stamp
        (signatures / ".updated").write_text(str(value))
    result = subprocess.run(
        [sys.executable, str(scanner), "scan", "fixture.pdf"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert "ClamAV signatures are unavailable" in result.stderr
