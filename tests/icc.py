"""Build a valid wide-gamut ICC profile, so the colour tests are self-contained.

The program's headline colour behaviour is "an iPhone's Display P3 pixels come
out as sRGB". Testing that needs an input tagged with a profile that is *not*
sRGB, and there is no way to get one out of Pillow: ``ImageCms.createProfile``
offers only sRGB, LAB and XYZ, and its ``colorTemp`` argument is ignored - a
5000 K request returns bytes identical to plain sRGB, verified.

The alternatives were to commit a profile lifted out of one of the owner's
photographs, or to skip the test unless a real photo happens to be present. Both
are worse than assembling one here: this is a hundred lines of struct packing,
it depends on nothing, and it makes the test deterministic on any machine.

The profile is a v4 matrix-shaper with Display P3 primaries, which is what makes
it genuinely wider than sRGB and therefore genuinely change pixel values on the
way in.

Reference: ICC.1:2010 (Profile version 4.3.0.0), sections 7.2 (header) and 10
(tag types).
"""

from __future__ import annotations

import struct

D50 = (0.9642, 1.0, 0.8249)
"""The PCS illuminant every ICC profile is adapted to (ICC.1:2010 section 7.2.16)."""

P3_PRIMARIES_D50 = {
    # Display P3 colorants, Bradford-adapted to D50. Red's Z is very slightly
    # negative in the published matrix; it is clamped to zero here because some
    # CMMs reject a negative colorant, and the few ten-thousandths lost are
    # irrelevant to a test that only needs "wider than sRGB".
    b"rXYZ": (0.51512, 0.24120, 0.00000),
    b"gXYZ": (0.29198, 0.69224, 0.04189),
    b"bXYZ": (0.15710, 0.06657, 0.78407),
}

GAMMA = 2.2


def _s15fixed16(value: float) -> bytes:
    """ICC's fixed-point number: signed, 15 integer bits, 16 fractional."""
    return struct.pack(">i", round(value * 65536))


def _xyz_tag(x: float, y: float, z: float) -> bytes:
    """XYZType (section 10.31)."""
    return b"XYZ " + b"\x00" * 4 + _s15fixed16(x) + _s15fixed16(y) + _s15fixed16(z)


def _curve_tag(gamma: float) -> bytes:
    """curveType with a single entry, which ICC defines as a gamma (10.6)."""
    return (
        b"curv"
        + b"\x00" * 4
        + struct.pack(">I", 1)
        + struct.pack(">H", round(gamma * 256))
    )


def _text_tag(text: str) -> bytes:
    """multiLocalizedUnicodeType, the v4 replacement for textDescription (10.15)."""
    encoded = text.encode("utf-16-be")
    return (
        b"mluc"
        + b"\x00" * 4
        + struct.pack(">I", 1)  # one record
        + struct.pack(">I", 12)  # record size
        + b"enUS"
        + struct.pack(">I", len(encoded))
        + struct.pack(">I", 28)  # offset from the start of this tag
        + encoded
    )


def _pad(data: bytes) -> bytes:
    """Tags are aligned to a four-byte boundary (section 7.3.5)."""
    remainder = len(data) % 4
    return data if remainder == 0 else data + b"\x00" * (4 - remainder)


def build_profile(description: str = "Test Wide Gamut RGB") -> bytes:
    """A complete, valid ICC v4 matrix-shaper RGB profile.

    The description matters to the program under test: ``imgconv.imaging.color``
    skips the transform when a profile describes itself as sRGB, so a profile
    used to prove that conversion happens must not be called sRGB.
    """
    tags: list[tuple[bytes, bytes]] = [
        (b"desc", _text_tag(description)),
        (b"cprt", _text_tag("No copyright, generated for testing")),
        (b"wtpt", _xyz_tag(*D50)),
    ]
    for signature, (x, y, z) in P3_PRIMARIES_D50.items():
        tags.append((signature, _xyz_tag(x, y, z)))
    for signature in (b"rTRC", b"gTRC", b"bTRC"):
        tags.append((signature, _curve_tag(GAMMA)))

    header_size = 128
    table_size = 4 + 12 * len(tags)
    offset = header_size + table_size

    table = struct.pack(">I", len(tags))
    body = b""
    for signature, data in tags:
        padded = _pad(data)
        table += signature + struct.pack(">II", offset, len(data))
        body += padded
        offset += len(padded)

    total = header_size + table_size + len(body)

    header = (
        struct.pack(">I", total)
        + b"none"  # preferred CMM: none in particular
        + struct.pack(">I", 0x04300000)  # version 4.3.0.0
        + b"mntr"  # display device
        + b"RGB "
        + b"XYZ "
        + b"\x00" * 12  # creation date; zero is permitted
        + b"acsp"  # the profile file signature
        + b"MSFT"
        + struct.pack(">I", 0)  # flags
        + b"\x00" * 4  # device manufacturer
        + b"\x00" * 4  # device model
        + b"\x00" * 8  # device attributes
        + struct.pack(">I", 0)  # rendering intent: perceptual
        + _s15fixed16(D50[0])
        + _s15fixed16(D50[1])
        + _s15fixed16(D50[2])
        + b"\x00" * 4  # profile creator
        + b"\x00" * 44  # profile ID and reserved
    )
    assert len(header) == header_size, len(header)

    return header + table + body
