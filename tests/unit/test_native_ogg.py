import random
import struct

import pytest

from experiments.native_ogg.ogg_core import (
    MAX_PACKETS,
    OggFormatError,
    build_ogg_fixture,
    ogg_crc,
    parse_ogg_vorbis,
)
from experiments.native_ogg.ogg_prepare import bitrate_is_approximately_preserved

pytestmark = pytest.mark.portable


def _page_offsets(native: bytes) -> list[tuple[int, int]]:
    offsets = []
    cursor = 0
    while cursor < len(native):
        count = native[cursor + 26]
        table_end = cursor + 27 + count
        end = table_end + sum(native[cursor + 27 : table_end])
        offsets.append((cursor, end))
        cursor = end
    return offsets


def _patch_page(native: bytes, page_index: int, offset: int, value: bytes) -> bytes:
    pages = _page_offsets(native)
    start, end = pages[page_index]
    page = bytearray(native[start:end])
    page[offset : offset + len(value)] = value
    page[22:26] = bytes(4)
    struct.pack_into("<I", page, 22, ogg_crc(page))
    return native[:start] + bytes(page) + native[end:]


def _fixture_packets(native: bytes) -> list[bytes]:
    packets: list[bytes] = []
    partial = bytearray()
    for start, end in _page_offsets(native):
        segment_count = native[start + 26]
        lacing_start = start + 27
        body_offset = lacing_start + segment_count
        for lace in native[lacing_start:body_offset]:
            partial.extend(native[body_offset : body_offset + lace])
            body_offset += lace
            if lace < 255:
                packets.append(bytes(partial))
                partial.clear()
    assert not partial
    return packets


def _page(
    packets: list[bytes], *, flags: int, granule: int, serial: int, sequence: int
) -> bytes:
    lacing = bytearray()
    body = bytearray()
    for packet in packets:
        offset = 0
        while len(packet) - offset >= 255:
            lacing.append(255)
            body.extend(packet[offset : offset + 255])
            offset += 255
        lacing.append(len(packet) - offset)
        body.extend(packet[offset:])
    page = bytearray(
        struct.pack(
            "<4sBBQIIIB",
            b"OggS",
            0,
            flags,
            granule,
            serial,
            sequence,
            0,
            len(lacing),
        )
    )
    page.extend(lacing)
    page.extend(body)
    struct.pack_into("<I", page, 22, ogg_crc(page))
    return bytes(page)


def test_pure_python_writer_builds_pages_crc_headers_and_tags() -> None:
    native = build_ogg_fixture()
    parsed = parse_ogg_vorbis(native, expected_frames=44_100)
    assert parsed.channels == 2
    assert parsed.rate == 44_100
    assert parsed.frames == 44_100
    assert parsed.nominal_bitrate == 128_000
    assert parsed.vendor == "native_ogg synthetic fixture"
    assert parsed.comments == (
        ("LOOPSTART", "4410"),
        ("LOOPLENGTH", "22050"),
        ("FIXTURE", "synthetic"),
    )
    assert parsed.audio_packet_count == 1
    assert parsed.page_count == 3
    pages = _page_offsets(native)
    assert native[pages[0][0] + 5] == 0x02
    assert native[pages[0][0] + 26] == 1
    assert native[pages[0][0] + 27] == 30
    assert struct.unpack_from("<Q", native, pages[0][0] + 6)[0] == 0
    assert struct.unpack_from("<Q", native, pages[1][0] + 6)[0] == 0
    assert native[pages[-1][0] + 5] == 0x04


def test_bitrate_class_comparison_has_a_bounded_tolerance() -> None:
    assert bitrate_is_approximately_preserved(128_000, 140_800)
    assert not bitrate_is_approximately_preserved(32_000, 48_000)
    assert not bitrate_is_approximately_preserved(128_000, 160_000)
    assert not bitrate_is_approximately_preserved(-1, 128_000)
    assert not bitrate_is_approximately_preserved(128_000, 0)


def _slow_ogg_crc(data: bytes | bytearray) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            crc = (
                ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
                if crc & 0x80000000
                else (crc << 1) & 0xFFFFFFFF
            )
    return crc


def test_table_driven_ogg_crc_matches_known_vector_and_slow_reference() -> None:
    assert ogg_crc(b"123456789") == 0x89A1897F
    randomizer = random.Random(0x0A66)
    for length in (0, 1, 2, 26, 27, 255, 1_024, 4_096):
        data = bytes(randomizer.randrange(256) for _ in range(length))
        assert ogg_crc(data) == _slow_ogg_crc(data)


def test_packet_reassembly_across_continued_pages() -> None:
    native = build_ogg_fixture(
        frames=88_200,
        vendor="v" * 900,
        max_segments_per_page=1,
    )
    parsed = parse_ogg_vorbis(native, expected_frames=88_200)
    pages = _page_offsets(native)
    assert parsed.page_count == len(pages)
    assert parsed.vendor == "v" * 900
    assert any(native[start + 5] & 0x01 for start, _ in pages[1:])


def test_parser_refuses_too_many_tiny_crc_valid_packets_promptly() -> None:
    native = build_ogg_fixture(
        audio_packets=(b"\x00",) * (MAX_PACKETS - 2),
    )
    with pytest.raises(OggFormatError, match="Ogg packet count exceeds limit"):
        parse_ogg_vorbis(native)


def test_vorbis_field_names_are_ascii_case_insensitive_only() -> None:
    upper = parse_ogg_vorbis(build_ogg_fixture(comments=(("LOOPSTART", "4410"),)))
    lower = parse_ogg_vorbis(build_ogg_fixture(comments=(("loopstart", "4410"),)))
    assert upper.comment_multiset == lower.comment_multiset
    punctuation = parse_ogg_vorbis(
        build_ogg_fixture(comments=(("FIELD NAME!?", "value"),))
    )
    punctuation_lower = parse_ogg_vorbis(
        build_ogg_fixture(comments=(("field name!?", "value"),))
    )
    assert punctuation.comment_multiset == punctuation_lower.comment_multiset

    with pytest.raises(OggFormatError, match="invalid Vorbis comment field"):
        parse_ogg_vorbis(build_ogg_fixture(comments=(("ß", "4410"),)))


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("capture", "invalid Ogg capture pattern"),
        ("truncated", "truncated Ogg page body"),
        ("segment table", "truncated Ogg segment table"),
        ("trailing", "trailing bytes after Ogg EOS page"),
        ("crc", "Ogg page CRC mismatch"),
        ("version", "unsupported Ogg bitstream version"),
        ("reserved flags", "reserved Ogg header-type flag set"),
        ("sequence", "Ogg page sequence gap"),
        ("serial", "chained or multiplexed Ogg streams are unsupported"),
        ("continuation", "Ogg continued-packet flag mismatch"),
        ("missing EOS", "missing Ogg EOS page"),
        ("early EOS", "trailing bytes after Ogg EOS page"),
        ("non-Vorbis", "missing or malformed Vorbis identification header"),
        ("six channels", "unsupported Vorbis channel profile"),
        ("wrong rate", "unsupported Vorbis sample-rate profile"),
        ("identification framing", "missing Vorbis identification framing bit"),
        ("comment framing", "missing Vorbis comment framing bit"),
        ("comment length", "oversized Vorbis vendor"),
        ("missing setup", "missing or malformed Vorbis setup header"),
        (
            "empty page granule",
            "Ogg page without completed packets has a granule position",
        ),
        ("granule", "final Ogg granule position differs from decoded frame count"),
        ("header granule", "Vorbis header page granule position must be zero"),
        (
            "identification alone",
            "Vorbis identification header must be alone on the BOS page",
        ),
        ("first audio fresh", "first Vorbis audio packet must begin on a fresh page"),
        ("headers before audio", "invalid Vorbis audio packet"),
    ],
)
def test_parser_rejects_malformed_or_unsupported_streams(
    case: str, reason: str
) -> None:
    native = build_ogg_fixture()
    if case == "capture":
        changed = bytearray(native)
        changed[0] = ord("X")
        native = bytes(changed)
    elif case == "truncated":
        native = native[:-1]
    elif case == "segment table":
        native = _patch_page(native, 0, 26, b"\xff")
    elif case == "trailing":
        native += b"\x00"
    elif case == "crc":
        changed = bytearray(native)
        changed[-1] ^= 1
        native = bytes(changed)
    elif case == "version":
        native = _patch_page(native, 0, 4, b"\x01")
    elif case == "reserved flags":
        native = _patch_page(native, 0, 5, b"\x82")
    elif case == "sequence":
        native = _patch_page(native, 0, 18, struct.pack("<I", 1))
    elif case == "serial":
        native = build_ogg_fixture(vendor="v" * 900, max_segments_per_page=1)
        native = _patch_page(native, 1, 14, struct.pack("<I", 7))
    elif case == "continuation":
        native = build_ogg_fixture(vendor="v" * 900, max_segments_per_page=1)
        native = _patch_page(native, 1, 5, b"\x03")
    elif case == "missing EOS":
        native = _patch_page(native, 2, 5, b"\x00")
    elif case == "early EOS":
        native = build_ogg_fixture(vendor="v" * 900, max_segments_per_page=1)
        native = _patch_page(native, 0, 5, b"\x06")
    elif case == "non-Vorbis":
        native = _patch_page(native, 0, 28, b"\x80")
    elif case == "six channels":
        native = build_ogg_fixture(channels=6)
    elif case == "wrong rate":
        native = build_ogg_fixture(rate=48_000)
    elif case == "identification framing":
        native = _patch_page(native, 0, 28 + 29, b"\x00")
    elif case == "comment framing":
        vendor_bytes = b"native_ogg synthetic fixture"
        comment_lengths = (14, 16, 17)
        comment_packet_bytes = (
            7
            + 4
            + len(vendor_bytes)
            + 4
            + sum(4 + length for length in comment_lengths)
            + 1
        )
        native = _patch_page(
            native,
            1,
            29 + comment_packet_bytes - 1,
            b"\x00",
        )
    elif case == "comment length":
        native = _patch_page(native, 1, 29 + 7, struct.pack("<I", 0xFFFFFFFF))
    elif case == "missing setup":
        native = build_ogg_fixture(setup_packet=b"")
    elif case == "empty page granule":
        native = build_ogg_fixture(vendor="v" * 900, max_segments_per_page=1)
        native = _patch_page(native, 1, 6, struct.pack("<Q", 0))
    elif case == "granule":
        native = _patch_page(native, 2, 6, struct.pack("<Q", 44_099))
    elif case == "header granule":
        native = _patch_page(native, 1, 6, struct.pack("<Q", 1))
    elif case == "identification alone":
        packets = _fixture_packets(native)
        serial = struct.unpack_from("<I", native, 14)[0]
        native = _page(packets, flags=0x06, granule=44_100, serial=serial, sequence=0)
    elif case == "first audio fresh":
        packets = _fixture_packets(native)
        serial = struct.unpack_from("<I", native, 14)[0]
        native = b"".join(
            [
                _page([packets[0]], flags=0x02, granule=0, serial=serial, sequence=0),
                _page(
                    packets[1:],
                    flags=0x04,
                    granule=44_100,
                    serial=serial,
                    sequence=1,
                ),
            ]
        )
    elif case == "headers before audio":
        packets = _fixture_packets(native)
        serial = struct.unpack_from("<I", native, 14)[0]
        native = b"".join(
            [
                _page([packets[0]], flags=0x02, granule=0, serial=serial, sequence=0),
                _page(
                    [packets[3]],
                    flags=0,
                    granule=0,
                    serial=serial,
                    sequence=1,
                ),
                _page(
                    packets[1:3],
                    flags=0x04,
                    granule=0,
                    serial=serial,
                    sequence=2,
                ),
            ]
        )

    with pytest.raises(OggFormatError, match=reason.replace(".", r"\.")):
        parse_ogg_vorbis(native, expected_frames=44_100)


def test_parser_rejects_unsupported_opus_packet_and_wrong_decoded_frame_count() -> None:
    native = _patch_page(build_ogg_fixture(), 0, 31, b"\x80")
    with pytest.raises(OggFormatError, match="identification header"):
        parse_ogg_vorbis(native)

    with pytest.raises(OggFormatError, match="decoded frame count"):
        parse_ogg_vorbis(build_ogg_fixture(), expected_frames=44_101)
