from pathlib import Path
import zlib

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
    """Original WPT ICC payload, independently decompressed with stdlib zlib."""
    from png import PngDocument

    document = PngDocument.load(assets_dir.joinpath('wpt', 'png', 'support', 'cICP-and-iCCP.png'))
    payload = document.find_chunks(b'iCCP')[0].data
    return zlib.decompress(payload.split(b'\0', 1)[1][1:])
