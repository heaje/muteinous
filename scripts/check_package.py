"""Build from the locked environment and smoke-test the resulting distributions."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        output = work / "dist"
        subprocess.run(
            [
                "uv",
                "build",
                "--no-build-isolation",
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
        environment = work / "venv"
        subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(environment)],
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
                "import muteinous; from importlib.metadata import version; "
                "print(version('muteinous'), muteinous.__file__)",
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
