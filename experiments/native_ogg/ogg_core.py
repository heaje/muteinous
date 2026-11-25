"""Pure-Python structural validation for one narrow Ogg Vorbis profile.

The parser deliberately does not decode audio. FFmpeg is used by the separate
manual experiment only; required tests can build and validate synthetic pages.
"""

import struct
from collections import Counter
from dataclasses import dataclass
from typing import NoReturn

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_PACKET_BYTES = 16 * 1024 * 1024
MAX_COMMENT_BYTES = 1024 * 1024
MAX_COMMENTS = 4096
MAX_PAGES = 100_000
MAX_PACKETS = 100_000
_PAGE_HEADER_BYTES = 27
_CRC_POLYNOMIAL = 0x04C11DB7


def _build_crc_table() -> tuple[int, ...]:
    table = []
    for byte in range(256):
        crc = byte << 24
        for _ in range(8):
            crc = (
                ((crc << 1) ^ _CRC_POLYNOMIAL) & 0xFFFFFFFF
                if crc & 0x80000000
                else (crc << 1) & 0xFFFFFFFF
            )
        table.append(crc)
    return tuple(table)


_CRC_TABLE = _build_crc_table()


class OggFormatError(ValueError):
    """An Ogg stream is malformed or outside the experiment's supported profile."""


@dataclass(frozen=True)
class VorbisInfo:
    channels: int
    rate: int
    frames: int
    vendor: str
    comments: tuple[tuple[str, str], ...]
    max_bitrate: int
    nominal_bitrate: int
    min_bitrate: int
    small_block_size: int
    large_block_size: int
    serial: int
    page_count: int
    audio_packet_count: int
    setup_bytes: int

    @property
    def comment_multiset(self) -> Counter[tuple[str, str]]:
        """Vorbis field names are case-insensitive; values are preserved exactly."""
        return Counter((_ascii_lower(name), value) for name, value in self.comments)


def _ascii_lower(value: str) -> str:
    return "".join(
        chr(ord(character) + 32) if "A" <= character <= "Z" else character
        for character in value
    )


def ogg_crc(data: bytes | bytearray) -> int:
    """Return the Ogg CRC-32 (poly 0x04C11DB7, non-reflected, init 0)."""
    crc = 0
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[((crc >> 24) ^ byte) & 0xFF]
    return crc


def _refuse(reason: str) -> NoReturn:
    raise OggFormatError(reason)


def _parse_identification(packet: bytes) -> tuple[int, int, int, int, int, int, int]:
    if len(packet) != 30 or packet[:7] != b"\x01vorbis":
        _refuse("missing or malformed Vorbis identification header")
    version, channels, rate, maximum, nominal, minimum, block, framing = (
        struct.unpack_from("<IBIiiiBB", packet, 7)
    )
    if version != 0:
        _refuse("unsupported Vorbis version")
    if channels != 2:
        _refuse("unsupported Vorbis channel profile")
    if rate != 44_100:
        _refuse("unsupported Vorbis sample-rate profile")
    if framing != 1:
        _refuse("missing Vorbis identification framing bit")
    small_exp, large_exp = block & 0x0F, block >> 4
    if not 6 <= small_exp <= large_exp <= 13:
        _refuse("invalid Vorbis block sizes")
    if any(value < -1 for value in (maximum, nominal, minimum)):
        _refuse("invalid Vorbis bitrate fields")
    if nominal > 0 and (
        (maximum > 0 and nominal > maximum) or (minimum > 0 and nominal < minimum)
    ):
        _refuse("inconsistent Vorbis bitrate fields")
    if maximum > 0 and minimum > 0 and minimum > maximum:
        _refuse("inconsistent Vorbis bitrate bounds")
    return (
        channels,
        rate,
        maximum,
        nominal,
        minimum,
        1 << small_exp,
        1 << large_exp,
    )


def _parse_comment(packet: bytes) -> tuple[str, tuple[tuple[str, str], ...]]:
    if len(packet) < 16 or packet[:7] != b"\x03vorbis":
        _refuse("missing or malformed Vorbis comment header")
    offset = 7

    def take_u32(label: str) -> int:
        nonlocal offset
        if offset + 4 > len(packet):
            _refuse(f"truncated Vorbis {label}")
        value = int(struct.unpack_from("<I", packet, offset)[0])
        offset += 4
        return value

    def take_string(length: int, label: str) -> bytes:
        nonlocal offset
        if length > MAX_COMMENT_BYTES:
            _refuse(f"oversized Vorbis {label}")
        end = offset + length
        if end < offset or end > len(packet):
            _refuse(f"truncated Vorbis {label}")
        value = packet[offset:end]
        offset = end
        return value

    vendor_len = take_u32("vendor length")
    try:
        vendor = take_string(vendor_len, "vendor").decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _refuse("invalid UTF-8 in Vorbis vendor")
    if "\x00" in vendor:
        _refuse("NUL byte in Vorbis vendor")
    count = take_u32("comment count")
    if count > MAX_COMMENTS:
        _refuse("too many Vorbis comments")
    comments: list[tuple[str, str]] = []
    total_bytes = vendor_len
    for _ in range(count):
        length = take_u32("comment length")
        total_bytes += length
        if total_bytes > MAX_COMMENT_BYTES:
            _refuse("oversized Vorbis comments")
        try:
            text = take_string(length, "comment").decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _refuse("invalid UTF-8 in Vorbis comment")
        if "\x00" in text:
            _refuse("NUL byte in Vorbis comment")
        name, separator, value = text.partition("=")
        if (
            not separator
            or not name
            or any(
                not character.isascii()
                or not 0x20 <= ord(character) <= 0x7D
                or character == "="
                for character in name
            )
        ):
            _refuse("invalid Vorbis comment field")
        comments.append((name, value))
    if offset != len(packet) - 1 or packet[offset] != 1:
        _refuse("missing Vorbis comment framing bit")
    return vendor, tuple(comments)


def _parse_pages(
    native: bytes,
) -> tuple[
    list[bytes],
    int,
    int,
    int,
    int,
    int | None,
    tuple[int, int] | None,
]:
    if not native:
        _refuse("empty Ogg stream")
    if len(native) > MAX_FILE_BYTES:
        _refuse("Ogg stream exceeds size limit")

    packets: list[bytes] = []
    partial = bytearray()
    cursor = 0
    expected_sequence = 0
    packet_count = 0
    audio_packet_count = 0
    serial: int | None = None
    prior_granule = 0
    eos_seen = False
    page_count = 0
    final_granule = -1
    packet_start_location: tuple[int, int] | None = None
    setup_end_page: int | None = None
    first_audio_start: tuple[int, int] | None = None

    while cursor < len(native):
        if eos_seen:
            _refuse("trailing bytes after Ogg EOS page")
        page_count += 1
        if page_count > MAX_PAGES:
            _refuse("Ogg page count exceeds limit")
        if cursor + _PAGE_HEADER_BYTES > len(native):
            _refuse("truncated Ogg page header")
        if native[cursor : cursor + 4] != b"OggS":
            _refuse("invalid Ogg capture pattern")
        version = native[cursor + 4]
        if version != 0:
            _refuse("unsupported Ogg bitstream version")
        flags = native[cursor + 5]
        if flags & ~0x07:
            _refuse("reserved Ogg header-type flag set")
        granule_raw, page_serial, sequence, checksum, segment_count = (
            struct.unpack_from("<QIIIB", native, cursor + 6)
        )
        if bool(flags & 0x01) != bool(partial):
            _refuse("Ogg continued-packet flag mismatch")
        if sequence != expected_sequence:
            _refuse("Ogg page sequence gap")
        expected_sequence += 1
        if serial is None:
            serial = page_serial
            if sequence != 0 or not flags & 0x02:
                _refuse("Ogg stream must start with BOS sequence zero")
        elif page_serial != serial:
            _refuse("chained or multiplexed Ogg streams are unsupported")
        elif flags & 0x02:
            _refuse("unexpected Ogg BOS page")

        table_start = cursor + _PAGE_HEADER_BYTES
        table_end = table_start + segment_count
        if table_end > len(native):
            _refuse("truncated Ogg segment table")
        lacing = native[table_start:table_end]
        body_size = sum(lacing)
        page_end = table_end + body_size
        if page_end > len(native):
            _refuse("truncated Ogg page body")
        page = bytearray(native[cursor:page_end])
        page[22:26] = bytes(4)
        if ogg_crc(page) != checksum:
            _refuse("Ogg page CRC mismatch")

        body_offset = table_end
        completed_packet = False
        page_index = page_count - 1
        page_has_audio_packet = False
        page_packet_starts = 0
        page_packet_completions = 0
        for segment_index, lace in enumerate(lacing):
            if not partial:
                packet_start_location = (page_index, segment_index)
                page_packet_starts += 1
            if packet_count >= 3:
                page_has_audio_packet = True
            end = body_offset + lace
            partial.extend(native[body_offset:end])
            if len(partial) > MAX_PACKET_BYTES:
                _refuse("Ogg packet exceeds size limit")
            body_offset = end
            if lace < 255:
                packet_count += 1
                if packet_count > MAX_PACKETS:
                    _refuse("Ogg packet count exceeds limit")
                if packet_start_location is None:
                    _refuse("invalid Ogg packet placement")
                if packet_count == 3:
                    setup_end_page = page_index
                elif packet_count == 4:
                    first_audio_start = packet_start_location
                packet_start_location = None
                page_packet_completions += 1
                if packet_count <= 3:
                    packets.append(bytes(partial))
                else:
                    if not partial or partial[0] & 1:
                        _refuse("invalid Vorbis audio packet")
                    audio_packet_count += 1
                partial.clear()
                completed_packet = True

        granule = -1 if granule_raw == 0xFFFFFFFFFFFFFFFF else granule_raw
        final_granule = granule
        if completed_packet and granule < 0:
            _refuse("Ogg completed packet has no granule position")
        if not completed_packet and granule >= 0:
            _refuse("Ogg page without completed packets has a granule position")
        if not page_has_audio_packet and granule >= 0 and granule != 0:
            _refuse("Vorbis header page granule position must be zero")
        if granule >= 0:
            if granule < prior_granule:
                _refuse("Ogg granule position moved backwards")
            prior_granule = granule

        is_eos = bool(flags & 0x04)
        if is_eos:
            if page_end != len(native):
                _refuse("trailing bytes after Ogg EOS page")
            if partial:
                _refuse("incomplete packet at Ogg EOS")
            eos_seen = True
        if page_index == 0 and (
            segment_count != 1
            or page_packet_starts != 1
            or page_packet_completions != 1
        ):
            _refuse("Vorbis identification header must be alone on the BOS page")
        cursor = page_end

    if not eos_seen:
        _refuse("missing Ogg EOS page")
    if partial:
        _refuse("incomplete final Ogg packet")
    if serial is None:
        _refuse("missing Ogg logical stream")
    return (
        packets,
        serial,
        page_count,
        final_granule,
        audio_packet_count,
        setup_end_page,
        first_audio_start,
    )


def parse_ogg_vorbis(
    native: bytes, *, expected_frames: int | None = None
) -> VorbisInfo:
    """Validate pages/headers and return metadata for stereo 44.1-kHz Vorbis."""
    (
        packets,
        serial,
        page_count,
        frames,
        audio_packet_count,
        setup_end_page,
        first_audio_start,
    ) = _parse_pages(native)
    if len(packets) < 3 or audio_packet_count < 1:
        _refuse("Ogg Vorbis stream is missing headers or audio packets")
    (
        channels,
        rate,
        maximum,
        nominal,
        minimum,
        small_block,
        large_block,
    ) = _parse_identification(packets[0])
    vendor, comments = _parse_comment(packets[1])
    if len(packets[2]) < 8 or packets[2][:7] != b"\x05vorbis":
        _refuse("missing or malformed Vorbis setup header")
    if not packets[2][7:]:
        _refuse("empty Vorbis setup header")
    if setup_end_page is None or first_audio_start is None:
        _refuse("Ogg Vorbis stream is missing headers or audio packets")
    if first_audio_start[0] <= setup_end_page or first_audio_start[1] != 0:
        _refuse("first Vorbis audio packet must begin on a fresh page")
    if frames <= 0:
        _refuse("invalid final Ogg granule position")
    if frames > 0x7FFFFFFFFFFFFFFF:
        _refuse("Ogg frame count exceeds supported range")
    if expected_frames is not None and frames != expected_frames:
        _refuse("final Ogg granule position differs from decoded frame count")
    return VorbisInfo(
        channels=channels,
        rate=rate,
        frames=frames,
        vendor=vendor,
        comments=comments,
        max_bitrate=maximum,
        nominal_bitrate=nominal,
        min_bitrate=minimum,
        small_block_size=small_block,
        large_block_size=large_block,
        serial=serial,
        page_count=page_count,
        audio_packet_count=audio_packet_count,
        setup_bytes=len(packets[2]),
    )


def build_ogg_fixture(
    *,
    frames: int = 44_100,
    comments: tuple[tuple[str, str], ...] = (
        ("LOOPSTART", "4410"),
        ("LOOPLENGTH", "22050"),
        ("FIXTURE", "synthetic"),
    ),
    vendor: str = "native_ogg synthetic fixture",
    channels: int = 2,
    rate: int = 44_100,
    nominal_bitrate: int = 128_000,
    serial: int = 0x4D555445,
    framing_bit: int = 1,
    setup_packet: bytes = b"\x05vorbis\x00",
    audio_packets: tuple[bytes, ...] = (b"\x00synthetic-audio-packet",),
    max_segments_per_page: int = 255,
) -> bytes:
    """Build a deterministic, structurally valid fixture; codec payloads are opaque."""
    if not 1 <= max_segments_per_page <= 255:
        raise ValueError("page segment limit must be from 1 through 255")
    if not 0 < frames <= 0x7FFFFFFFFFFFFFFF:
        raise ValueError("invalid fixture frame count")
    identification = b"\x01vorbis" + struct.pack(
        "<IBIiiiBB",
        0,
        channels,
        rate,
        -1,
        nominal_bitrate,
        -1,
        0xB8,
        framing_bit,
    )
    vendor_bytes = vendor.encode("utf-8")
    comment_packet = bytearray(b"\x03vorbis")
    comment_packet.extend(struct.pack("<I", len(vendor_bytes)))
    comment_packet.extend(vendor_bytes)
    comment_packet.extend(struct.pack("<I", len(comments)))
    for name, value in comments:
        encoded = f"{name}={value}".encode("utf-8")
        comment_packet.extend(struct.pack("<I", len(encoded)))
        comment_packet.extend(encoded)
    comment_packet.append(1)
    packets = [identification, bytes(comment_packet), setup_packet, *audio_packets]

    segments: list[tuple[int, bytes, bool, int]] = []
    for packet_index, packet in enumerate(packets):
        offset = 0
        while len(packet) - offset >= 255:
            segments.append((255, packet[offset : offset + 255], False, packet_index))
            offset += 255
        tail = packet[offset:]
        segments.append((len(tail), tail, True, packet_index))

    page_segments: list[tuple[int, bytes, bool, int]] = []
    pages: list[tuple[list[tuple[int, bytes, bool, int]], bool]] = []
    continued = False

    def finish_page() -> None:
        nonlocal continued, page_segments
        if not page_segments:
            return
        pages.append((page_segments, continued))
        continued = not page_segments[-1][2]
        page_segments = []

    for segment in segments:
        lace, _, packet_complete, packet_index = segment
        del lace
        if (
            packet_index >= 3
            and page_segments
            and not any(item[3] >= 3 for item in page_segments)
        ):
            finish_page()
        page_segments.append(segment)
        if (
            len(page_segments) >= max_segments_per_page
            or (packet_index == 0 and packet_complete)
            or (packet_index == 2 and packet_complete)
        ):
            finish_page()
    finish_page()

    output = bytearray()
    for page_sequence, (page_segments, page_continued) in enumerate(pages):
        flags = (0x01 if page_continued else 0) | (0x02 if page_sequence == 0 else 0)
        if page_sequence == len(pages) - 1:
            flags |= 0x04
        completed = [segment for segment in page_segments if segment[2]]
        if not completed:
            granule = 0xFFFFFFFFFFFFFFFF
        elif any(segment[3] >= 3 for segment in completed):
            granule = frames
        else:
            granule = 0
        lacing = bytes(segment[0] for segment in page_segments)
        body = b"".join(segment[1] for segment in page_segments)
        header = bytearray(
            struct.pack(
                "<4sBBQIIIB",
                b"OggS",
                0,
                flags,
                granule,
                serial,
                page_sequence,
                0,
                len(page_segments),
            )
        )
        page = header + lacing + body
        struct.pack_into("<I", page, 22, ogg_crc(page))
        output.extend(page)
    return bytes(output)
