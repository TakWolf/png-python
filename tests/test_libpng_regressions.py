"""Pure Python counterparts of selected libpng regression-test scenarios."""

import hashlib
import json
from io import BytesIO
from pathlib import Path
from struct import iter_unpack

import pytest

from png import PngCrcError, PngDocument, PngImage, PngLimitError, PngParseError


class BoundedReader(BytesIO):
    def read(self, size: int = -1) -> bytes:
        assert 0 <= size <= 65536
        return super().read(size)


def test_libpng_fixture_provenance(libpng_dir: Path) -> None:
    manifest = json.loads(libpng_dir.joinpath('SOURCE.json').read_text())
    assert manifest['repository'] == 'https://github.com/pnggroup/libpng'
    assert manifest['version'] == '1.6.59'
    assert manifest['tag'] == manifest['describe'] == 'v1.6.59'
    assert manifest['commit'] == 'cd952f49f95bb27154ae77dbb103032d95f6e580'
    records = manifest['files']
    notices = {entry['path']: entry['upstream_path'] for entry in records if not entry['path'].endswith('.png')}
    assert notices == {'CONTRIB-NOTICE.txt': 'contrib/README.txt', 'LICENSE.txt': 'LICENSE'}
    assert len({entry['path'] for entry in records}) == len(records)
    assert len(records) == 141
    assert len(list(libpng_dir.glob('*.png'))) == 106
    assert len(list(libpng_dir.joinpath('png-3').glob('*.png'))) == 1
    assert len(list(libpng_dir.joinpath('badpal').glob('*.png'))) == 9
    assert len(list(libpng_dir.joinpath('crashers').glob('*.png'))) == 23
    for entry in records:
        assert hashlib.sha256(libpng_dir.joinpath(entry['path']).read_bytes()).hexdigest() == entry['sha256']
        if entry['path'].endswith('.png'):
            assert Path(entry['upstream_path']).relative_to('contrib/testpngs').as_posix() == entry['path']
    expected = {entry['path'] for entry in records if entry['path'].endswith('.png')}
    assert len(expected) == 139
    assert {path.relative_to(libpng_dir).as_posix() for path in libpng_dir.rglob('*.png')} == expected


@pytest.mark.parametrize('compact', [False, True])
def test_upstream_crashers_fail_with_bounded_reads(libpng_crasher_file: Path, compact: bool) -> None:
    stream = BoundedReader(libpng_crasher_file.read_bytes())
    with pytest.raises(PngParseError) as caught:
        PngImage.parse(stream, compact=compact)
    assert not isinstance(caught.value, PngLimitError)
    assert not stream.closed


def test_adler_failure_belongs_to_pixel_decoding(libpng_dir: Path) -> None:
    document = PngDocument.load(libpng_dir.joinpath('crashers', 'badadler.png'))
    with pytest.raises(PngParseError, match='zlib'):
        PngImage.from_document(document)


@pytest.mark.parametrize('name,kind', [('badcrc.png', b'IDAT'), ('bad_iCCP.png', b'IHDR')])
def test_upstream_crc_errors_identify_the_first_damaged_chunk(libpng_dir: Path, name: str, kind: bytes) -> None:
    with pytest.raises(PngCrcError) as caught:
        PngImage.load(libpng_dir.joinpath('crashers', name))
    assert caught.value.chunk_type == kind


@pytest.mark.parametrize('compact', [False, True])
def test_upstream_short_palettes_recover_missing_entries_as_opaque_black(
    libpng_palette_file: Path, compact: bool
) -> None:
    document = PngDocument.load(libpng_palette_file)
    palette_bytes = document.find_chunks(b'PLTE')[0].data
    original_palette = list(iter_unpack('BBB', palette_bytes))
    assert not document.find_chunks(b'tRNS')
    image = PngImage.from_document(document, compact=compact)
    bitmap = [list(row) for row in image.bitmap]
    assert max(map(max, bitmap)) >= len(original_palette)
    assert image.palette[: len(original_palette)] == original_palette
    assert all(color == (0, 0, 0) for color in image.palette[len(original_palette) :])
    if libpng_palette_file.name.startswith('small-palette') or libpng_palette_file.name == 'regression-palette-8.png':
        indices = list(range(1 << image.header.bit_depth))
        if libpng_palette_file.name == 'small-palette-8.png':
            indices = indices[1:] + indices[:1]
        assert bitmap == [indices]
    expected = []
    for row in bitmap:
        pixels = []
        for index in row:
            color = original_palette[index] if index < len(original_palette) else (0, 0, 0)
            pixels.extend((*color, 255))
        expected.append(pixels)
    assert image.to_rgba().bitmap == expected
    restored = PngImage.parse(image.dump_to_bytes())
    assert restored.bitmap == bitmap
    assert restored.palette == image.palette
    assert document.find_chunks(b'PLTE')[0].data == palette_bytes
