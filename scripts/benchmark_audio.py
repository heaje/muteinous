"""Optional Linux codec experiment; requires FFmpeg/ffprobe and GNU time.

Run from an installed checkout: python scripts/benchmark_audio.py
The production package does not depend on these benchmark tools.
"""

import argparse
import hashlib
import json
import math
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from muteinous.core.audio.pcm import BLOCK_FRAMES, PCMFormat, Representation, censor_blocks
from muteinous.core.audio.wav import WaveStorage

_CASES: list[tuple[Representation, int, int, int, str, int]] = [
    ("u8", 8000, 1, 4, "mono", 2),
    ("s16", 16000, 1, 4, "mono", 2),
    ("s24", 48000, 2, 3, "stereo", 2),
    ("s32", 96000, 6, 63, "5.1", 2),
    ("f32", 48000, 2, 3, "stereo", 2),
    ("f64", 44100, 1, 4, "mono", 2),
    ("s24", 48000, 6, 63, "5.1", 20),
]


def raw_blocks(path: Path, info: PCMFormat) -> Iterator[bytes]:
    with path.open("rb") as stream:
        while block := stream.read(BLOCK_FRAMES * info.frame_bytes):
            yield block


def fixture(path: Path, info: PCMFormat) -> None:
    rng = random.Random(19)
    with path.open("wb") as stream:
        for start in range(0, info.frames, BLOCK_FRAMES):
            block = bytearray()
            for frame in range(start, min(start + BLOCK_FRAMES, info.frames)):
                for channel in range(info.channels):
                    # Alternating silence, tone and seeded noise; not a speech corpus.
                    phase = frame // (info.rate // 4) % 4
                    value = (
                        0.0
                        if phase == 0
                        else 0.6
                        * math.sin(2 * math.pi * (220 + channel * 30) * frame / info.rate)
                    )
                    if phase == 3:
                        value = rng.uniform(-0.9, 0.9)
                    if info.representation.startswith("f"):
                        block.extend(
                            struct.pack("<f" if info.width == 4 else "<d", value)
                        )
                    else:
                        unsigned = info.representation == "u8"
                        integer = round(value * ((1 << (info.width * 8 - 1)) - 1))
                        block.extend(
                            (integer + (128 if unsigned else 0)).to_bytes(
                                info.width, "little", signed=not unsigned
                            )
                        )
            stream.write(block)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def edit(info: PCMFormat, blocks: Iterator[bytes]) -> Iterator[bytes]:
    return censor_blocks(
        info, blocks, [(0.4, 0.8)], before=0.03, after=0.03, fade=0.02
    )


def worker(operation: str, info: PCMFormat, source: Path, output: Path) -> None:
    storage = WaveStorage()
    if operation == "encode":
        storage.write(output, info, raw_blocks(source, info))
    elif operation == "decode":
        with storage.open(source) as reader, output.open("wb") as stream:
            assert reader.info == info
            for block in reader.blocks():
                stream.write(block)
    elif operation == "wav-edit":
        with storage.open(source) as reader:
            storage.write(output, reader.info, edit(reader.info, reader.blocks()))
    elif operation == "raw-edit":
        with output.open("wb") as stream:
            for block in edit(info, raw_blocks(source, info)):
                stream.write(block)
    else:
        raise ValueError(operation)


def trial(
    root: Path, source: Path, info: PCMFormat, layout: str, codec: str
) -> dict[str, Any]:
    if codec == "flac" and info.representation.startswith("f"):
        return {"excluded": "FLAC is integer PCM only; no float quantization"}
    if codec == "wavpack" and info.representation == "f64":
        return {"excluded": "FFmpeg WavPack encoder has float32, not float64 input"}
    scratch = root / codec
    scratch.mkdir()
    encoded = scratch / {
        "wav": "source.wav",
        "flac": "source.flac",
        "wavpack": "source.wv",
    }[codec]
    decoded = scratch / "decoded.raw"
    edited_raw = scratch / "edited.raw"
    edited = scratch / ("edited" + encoded.suffix)
    metrics = root / "rss.txt"
    peak = 0
    rss = 0
    times: dict[str, float] = {}
    fmt = info.representation + ("le" if info.width > 1 else "")
    spec = json.dumps(info.__dict__)
    ffmpeg = ["ffmpeg", "-nostdin", "-v", "error", "-threads", "1"]

    def measure(name: str, command: list[str]) -> None:
        nonlocal peak, rss
        started = time.perf_counter()
        subprocess.run(
            ["/usr/bin/time", "-f", "%M", "-o", str(metrics), *command], check=True
        )
        times[name] = round(time.perf_counter() - started, 4)
        rss = max(rss, int(metrics.read_text().strip()))
        peak = max(peak, sum(p.stat().st_size for p in scratch.iterdir()))

    def python_op(name: str, operation: str, src: Path, dst: Path) -> None:
        measure(
            name,
            [sys.executable, __file__, "--worker", operation, spec, str(src), str(dst)],
        )

    def encode(name: str, src: Path, dst: Path) -> None:
        measure(
            name,
            [
                *ffmpeg,
                "-f",
                fmt,
                "-ar",
                str(info.rate),
                "-ac",
                str(info.channels),
                "-channel_layout",
                layout,
                "-i",
                str(src),
                "-c:a",
                codec,
                "-threads",
                "1",
                str(dst),
            ],
        )

    def decode(name: str, src: Path, dst: Path) -> None:
        measure(
            name, [*ffmpeg, "-i", str(src), "-c:a", "pcm_" + fmt, "-f", fmt, str(dst)]
        )

    try:
        if codec == "wav":
            python_op("encode", "encode", source, encoded)
            python_op("decode", "decode", encoded, decoded)
        else:
            encode("encode", source, encoded)
            decode("decode", encoded, decoded)
        exact = digest(source) == digest(decoded)
        probe = json.loads(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_streams",
                    "-of",
                    "json",
                    str(encoded),
                ]
            )
        )["streams"][0]
        # A missing precision/layout is not evidence of preserved metadata.
        bits = (
            int(probe.get("bits_per_raw_sample", "0"))
            if probe.get("bits_per_raw_sample", "0") != "N/A"
            else 0
        )
        bits = bits or int(probe.get("bits_per_sample", 0))
        if not bits and probe.get("sample_fmt") in ("flt", "fltp", "dbl", "dblp"):
            bits = 32 if probe["sample_fmt"].startswith("flt") else 64
        metadata = (
            int(probe["sample_rate"]) == info.rate
            and probe["channels"] == info.channels
            and probe.get("channel_layout") == layout
            and bits == info.width * 8
            and decoded.stat().st_size == info.frames * info.frame_bytes
        )
        encoded_bytes = encoded.stat().st_size
        if codec == "wav":
            decoded.unlink()
            python_op("edit", "wav-edit", encoded, edited)
            python_op("edit_decode", "decode", edited, decoded)
        else:
            python_op("edit_pcm", "raw-edit", decoded, edited_raw)
            decoded.unlink()
            encode("edit_encode", edited_raw, edited)
            edited_raw.unlink()
            decode("edit_decode", edited, decoded)
        reference = hashlib.sha256()
        for block in edit(info, raw_blocks(source, info)):
            reference.update(block)
        return {
            "exact": exact,
            "metadata": metadata,
            "edited_exact": digest(decoded) == reference.hexdigest(),
            "encoded_bytes": encoded_bytes,
            "peak_scratch_bytes": peak,
            "peak_child_rss_kib": rss,
            "seconds": times,
            "probe": {
                key: probe.get(key)
                for key in (
                    "sample_fmt",
                    "bits_per_sample",
                    "bits_per_raw_sample",
                    "channel_layout",
                )
            },
        }
    except subprocess.CalledProcessError as error:
        return {"excluded": f"tool exit {error.returncode}"}
    finally:
        shutil.rmtree(scratch)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(
            sys.argv[2],
            PCMFormat(**json.loads(sys.argv[3])),
            Path(sys.argv[4]),
            Path(sys.argv[5]),
        )
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=int, choices=range(len(_CASES)), action="append")
    args = parser.parse_args()
    print(
        subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0],
        flush=True,
    )
    with tempfile.TemporaryDirectory(prefix="audio-benchmark-") as directory:
        root = Path(directory)
        source = root / "fixture.raw"
        for index in args.case if args.case is not None else range(len(_CASES)):
            rep, rate, channels, mask, layout, seconds = _CASES[index]
            info = PCMFormat(rate, channels, rep, seconds * rate, mask)
            fixture(source, info)
            result = {
                codec: trial(root, source, info, layout, codec)
                for codec in ("wav", "flac", "wavpack")
            }
            print(
                json.dumps(
                    {
                        "case": info.__dict__,
                        "raw_bytes": source.stat().st_size,
                        "results": result,
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
