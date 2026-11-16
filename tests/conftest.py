import zlib
from pathlib import Path
from struct import pack, unpack_from

import pytest


@pytest.fixture(scope='session')
def project_root_dir() -> Path:
    return Path(__file__).parents[1]


@pytest.fixture(scope='session')
def assets_dir(project_root_dir: Path) -> Path:
    return project_root_dir.joinpath('assets')


@pytest.fixture(scope='session')
def png_suite_dir(assets_dir: Path) -> Path:
    return assets_dir.joinpath('png-suite')


@pytest.fixture(scope='session')
def icc_profile_bytes(assets_dir: Path) -> bytes:
    """Unmodified, structurally complete official ICC v2 sRGB profile."""
    return assets_dir.joinpath('icc', 'sRGB2014.icc').read_bytes()


@pytest.fixture(scope='session')
def gray_icc_profile_bytes(icc_profile_bytes: bytes) -> bytes:
    """In-memory v2.4 gray model vector derived from the official RGB profile."""
    (count,) = unpack_from('>I', icc_profile_bytes, 128)
    tags = {}
    for index in range(count):
        signature, offset, size = unpack_from('>4sII', icc_profile_bytes, 132 + 12 * index)
        if signature in (b'desc', b'cprt', b'wtpt', b'chad', b'rTRC'):
            tags[b'kTRC' if signature == b'rTRC' else signature] = icc_profile_bytes[offset : offset + size]
    header = bytearray(icc_profile_bytes[:128])
    header[9] = 0x40
    header[16:20] = b'GRAY'
    header[84:100] = bytes(16)
    table = bytearray()
    body = bytearray()
    for signature, value in tags.items():
        table.extend(pack('>4sII', signature, 132 + 12 * len(tags) + len(body), len(value)))
        body.extend(value)
        body.extend(bytes(-len(body) % 4))
    result = bytes(header) + pack('>I', len(tags)) + bytes(table) + bytes(body)
    return pack('>I', len(result)) + result[4:]


@pytest.fixture(scope='session')
def truncated_icc_profile_bytes(assets_dir: Path) -> bytes:
    """Original WPT ICC payload, independently decompressed with stdlib zlib."""
    from png import PngDocument

    document = PngDocument.load(assets_dir.joinpath('wpt', 'png', 'support', 'cICP-and-iCCP.png'))
    payload = document.find_chunks(b'iCCP')[0].data
    return zlib.decompress(payload.split(b'\0', 1)[1][1:])
