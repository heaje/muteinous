"""Manual libvorbis identity re-encode and measured generation-loss control."""

from pathlib import Path
from tempfile import TemporaryDirectory

from .ffmpeg_tools import OggFFmpegTools
from .manual_support import create_source_assets, snapshot
from .ogg_core import parse_ogg_vorbis
from .ogg_prepare import (
    INFO,
    MAX_OUTSIDE_ABS_ERROR,
    MIN_OUTSIDE_SNR_DB,
    QualityPolicy,
    bitrate_is_approximately_preserved,
    measure_lossy_effects,
    verify_lossy_reconstruction,
)


def main() -> None:
    tools = OggFFmpegTools.discover()
    print(f"PASS: {tools.version}")
    print("PASS: Ogg muxer/demuxer, libvorbis encoder, Vorbis decoder available")

    with TemporaryDirectory(prefix="muteinous-native-ogg-probe-") as private:
        root = Path(private)
        assets, originals, metadata = create_source_assets(root, tools, ("probe",))
        source = parse_ogg_vorbis(assets["probe"], expected_frames=INFO.frames)
        if source.comments != metadata["probe"].comments:
            raise AssertionError("source tags changed after pure-Python parse")
        if source.nominal_bitrate <= 0:
            raise AssertionError("source has no nominal bitrate for reconstruction")

        control_pcm = root / "probe.source-decoded.f32le"
        control_native = root / "probe.identity-control.ogg"
        tools.encode_vorbis(
            "probe-control",
            control_pcm,
            control_native,
            INFO,
            nominal_bitrate=source.nominal_bitrate,
            comments=source.comments,
        )
        rebuilt = control_native.read_bytes()
        rebuilt_info = parse_ogg_vorbis(rebuilt, expected_frames=INFO.frames)
        if rebuilt_info.comment_multiset != source.comment_multiset:
            raise AssertionError("identity re-encode did not preserve user comments")
        if not bitrate_is_approximately_preserved(
            source.nominal_bitrate, rebuilt_info.nominal_bitrate
        ):
            raise AssertionError("identity re-encode changed the bitrate class")

        decoded_path = root / "probe.identity-decoded.f32le"
        tools.decode("probe-control", control_native, decoded_path, INFO)
        control_decoded = decoded_path.read_bytes()
        if len(control_decoded) != INFO.frames * INFO.frame_bytes:
            raise AssertionError("identity output frame count differs from source")

        policy = QualityPolicy()
        verify_lossy_reconstruction(
            "probe-control",
            originals["probe"],
            originals["probe"],
            control_decoded,
            (),
            INFO,
            policy=policy,
        )
        control_metrics = measure_lossy_effects(
            originals["probe"], control_decoded, (), INFO, policy=policy
        )
        control_region = control_metrics.outside_regions[0]
        size_change = len(rebuilt) - len(assets["probe"])
        before = snapshot(root)
        if root.exists() is False:
            raise AssertionError("probe scratch unexpectedly disappeared")

        print(
            "PASS: pure-Python parser validated real libvorbis output "
            f"({source.page_count} source pages, {source.audio_packet_count} audio packets)"
        )
        print(
            f"PASS: identity control preserved {rebuilt_info.frames} decoded frames, "
            f"{rebuilt_info.channels} channels at {rebuilt_info.rate} Hz"
        )
        print(
            "MEASURE: identity generation loss "
            f"SNR={control_region.snr_db:.3f} dB, "
            f"max_abs_error={control_region.maximum_absolute_error:.8f}"
        )
        print(
            f"MEASURE: source nominal={source.nominal_bitrate} bit/s, "
            f"rebuilt nominal={rebuilt_info.nominal_bitrate} bit/s"
        )
        print(
            f"MEASURE: Ogg bytes source={len(assets['probe'])}, "
            f"identity={len(rebuilt)}, delta={size_change:+d}"
        )
        print(
            f"MEASURE: source vendor={source.vendor!r}; "
            f"identity vendor={rebuilt_info.vendor!r}"
        )
        print(
            "POLICY: outside-region gates "
            f"SNR>={MIN_OUTSIDE_SNR_DB:.1f} dB and "
            f"max_abs_error<={MAX_OUTSIDE_ABS_ERROR:.3f}; "
            f"edit guard={policy.guard_frames} frames"
        )
        if snapshot(root) != before:
            raise AssertionError("identity probe unexpectedly changed source files")
        print("PASS: identity control was read-only with respect to its source")

    if root.exists():
        raise AssertionError("probe scratch was not removed")
    print("PASS: disposable probe directory removed")


if __name__ == "__main__":
    main()
