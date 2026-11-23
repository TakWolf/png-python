import zlib
from pathlib import Path
from struct import pack, unpack_from

import pytest

_PROJECT_ROOT_DIR = Path(__file__).parents[1]
_ASSETS_DIR = _PROJECT_ROOT_DIR.joinpath('assets')
_PNG_SUITE_DIR = _ASSETS_DIR.joinpath('png-suite')
_WPT_DIR = _ASSETS_DIR.joinpath('wpt')
_WPT_PNG_DIR = _WPT_DIR.joinpath('png', 'support')
_APNG_DIR = _WPT_DIR.joinpath('png', 'apng')


@pytest.fixture(scope='session')
def project_root_dir() -> Path:
    return _PROJECT_ROOT_DIR


@pytest.fixture(scope='session')
def assets_dir() -> Path:
    return _ASSETS_DIR


@pytest.fixture(scope='session')
def png_suite_dir() -> Path:
    return _PNG_SUITE_DIR


@pytest.fixture(scope='session')
def wpt_dir() -> Path:
    return _WPT_DIR


@pytest.fixture(scope='session')
def wpt_png_dir() -> Path:
    return _WPT_PNG_DIR


@pytest.fixture(scope='session')
def apng_dir() -> Path:
    return _APNG_DIR


@pytest.fixture(params=sorted(path.name for path in _PNG_SUITE_DIR.glob('*.png') if not path.name.startswith('x')))
def png_suite_file(png_suite_dir: Path, request) -> Path:
    return png_suite_dir.joinpath(request.param)


@pytest.fixture(params=sorted(path.name for path in _PNG_SUITE_DIR.glob('x*.png')))
def png_suite_invalid_file(png_suite_dir: Path, request) -> Path:
    return png_suite_dir.joinpath(request.param)


@pytest.fixture(params=sorted(path.name for path in _PNG_SUITE_DIR.glob('basn*.png')))
def png_suite_base_file(png_suite_dir: Path, request) -> Path:
    return png_suite_dir.joinpath(request.param)


@pytest.fixture(params=sorted(path.name for path in _WPT_PNG_DIR.glob('*.png')))
def wpt_png_file(wpt_png_dir: Path, request) -> Path:
    return wpt_png_dir.joinpath(request.param)


@pytest.fixture(params=sorted(path.name for path in _APNG_DIR.joinpath('support').glob('[0-9]*.png')))
def apng_file(apng_dir: Path, request) -> Path:
    return apng_dir.joinpath('support', request.param)


@pytest.fixture(
    params=sorted(
        path.name
        for path in _APNG_DIR.glob('*.html')
        if 'rel="match"' in path.read_text() and path.name != 'fDAT-inherits-cICP.html'
    )
)
def apng_visual_file(apng_dir: Path, request) -> Path:
    return apng_dir.joinpath(request.param)


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
def truncated_icc_profile_bytes(wpt_png_dir: Path) -> bytes:
    """Original WPT ICC payload, independently decompressed with stdlib zlib."""
    from png import PngDocument

    document = PngDocument.load(wpt_png_dir.joinpath('cICP-and-iCCP.png'))
    payload = document.find_chunks(b'iCCP')[0].data
    return zlib.decompress(payload.split(b'\0', 1)[1][1:])
