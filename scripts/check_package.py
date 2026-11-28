"""Build from the locked environment and smoke-test the resulting distributions."""

import shutil
import subprocess
import sys
import tempfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from tarfile import open as open_tar
from zipfile import ZipFile


def metadata_version(data: bytes) -> str:
    version = BytesParser().parsebytes(data)["Version"]
    if not version:
        raise RuntimeError("Distribution metadata is missing its version")
    return str(version)


def validate_versions(wheel: Path, sdist: Path, expected: str) -> None:
    with ZipFile(wheel) as archive:
        (name,) = (
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        wheel_version = metadata_version(archive.read(name))
    with open_tar(sdist, "r:gz") as archive:
        (member,) = (
            member
            for member in archive.getmembers()
            if len(PurePosixPath(member.name).parts) == 2
            and PurePosixPath(member.name).name == "PKG-INFO"
        )
        stream = archive.extractfile(member)
        if stream is None:
            raise RuntimeError("Source distribution has no readable PKG-INFO")
        with stream:
            sdist_version = metadata_version(stream.read())
    if wheel_version != expected or sdist_version != expected:
        raise RuntimeError(
            f"Version mismatch: SCM={expected}, wheel={wheel_version}, "
            f"sdist={sdist_version}"
        )


def validate_licenses(wheel: Path, sdist: Path, root: Path) -> None:
    expected = {name: (root / name).read_bytes() for name in ("LICENSE", "NOTICE")}
    with ZipFile(wheel) as archive:
        (metadata,) = (
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        prefix = metadata.removesuffix("METADATA")
        message = BytesParser().parsebytes(archive.read(metadata))
        if message["License-Expression"] != "Apache-2.0":
            raise RuntimeError("Wheel has incorrect license expression")
        if set(message.get_all("License-File", [])) != set(expected):
            raise RuntimeError("Wheel has incorrect license-file metadata")
        for name, contents in expected.items():
            if archive.read(f"{prefix}licenses/{name}") != contents:
                raise RuntimeError(f"Wheel has incorrect {name} contents")
    with open_tar(sdist, "r:gz") as archive:
        (member,) = (
            member
            for member in archive.getmembers()
            if len(PurePosixPath(member.name).parts) == 2
            and PurePosixPath(member.name).name == "PKG-INFO"
        )
        prefix = member.name.removesuffix("PKG-INFO")
        stream = archive.extractfile(member)
        if stream is None:
            raise RuntimeError("Source distribution has no readable PKG-INFO")
        with stream:
            message = BytesParser().parsebytes(stream.read())
        if message["License-Expression"] != "Apache-2.0":
            raise RuntimeError("Source distribution has incorrect license expression")
        if set(message.get_all("License-File", [])) != set(expected):
            raise RuntimeError("Source distribution has incorrect license-file metadata")
        for name, contents in expected.items():
            stream = archive.extractfile(f"{prefix}{name}")
            if stream is None:
                raise RuntimeError(f"Source distribution has no readable {name}")
            with stream:
                if stream.read() != contents:
                    raise RuntimeError(f"Source distribution has incorrect {name} contents")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    expected = subprocess.check_output(
        [sys.executable, "-m", "setuptools_scm"], cwd=root, text=True
    ).strip()
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        output = work / "dist"
        subprocess.run(
            [
                "uv",
                "build",
                "--no-build-isolation",
                "--no-python-downloads",
                "--python",
                sys.executable,
                "--out-dir",
                str(output),
            ],
            cwd=root,
            check=True,
        )
        wheels = list(output.glob("*.whl"))
        sdists = list(output.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise RuntimeError("Expected one wheel and one source distribution")
        validate_versions(wheels[0], sdists[0], expected)
        validate_licenses(wheels[0], sdists[0], root)
        environment = work / "venv"
        subprocess.run(
            [
                "uv",
                "venv",
                "--no-python-downloads",
                "--python",
                sys.executable,
                str(environment),
            ],
            check=True,
        )
        interpreter = environment / (
            "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
        )
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(interpreter),
                "--no-deps",
                "--offline",
                "--no-python-downloads",
                str(wheels[0]),
            ],
            cwd=work,
            check=True,
        )
        subprocess.run(
            [
                str(interpreter),
                "-I",
                "-c",
                "import sys; from pathlib import Path; import muteinous; "
                "from importlib.metadata import version; "
                "assert version('muteinous') == sys.argv[1]; "
                "assert Path(muteinous.__file__).resolve().is_relative_to("
                "Path(sys.prefix).resolve()); "
                "print(version('muteinous'), muteinous.__file__)",
                expected,
            ],
            cwd=work,
            check=True,
        )
        target = root / "dist"
        target.mkdir(exist_ok=True)
        for artifact in (*wheels, *sdists):
            shutil.copy2(artifact, target / artifact.name)


if __name__ == "__main__":
    main()
