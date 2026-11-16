import zlib
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from struct import pack

import pytest

from png import (
    PngAnimation,
    PngChunk,
    PngColorType,
    PngDocument,
    PngFilterType,
    PngFrame,
    PngFrameControl,
    PngHeader,
    PngImage,
    PngInterlaceMethod,
    PngParseError,
    PngValidationError,
)

_SUITE_DIR = Path(__file__).parents[1].joinpath('assets', 'png-suite')
_VALID_NAMES = sorted(path.name for path in _SUITE_DIR.glob('*.png') if not path.name.startswith('x'))
_BASE_NAMES = sorted(path.name for path in _SUITE_DIR.glob('basn*.png'))


@pytest.mark.parametrize('name', _VALID_NAMES)
def test_pngsuite_pixel_roundtrip(png_suite_dir: Path, tmp_path: Path, name: str) -> None:
    original = PngImage.load(png_suite_dir.joinpath(name))
    original.validate()
    destination = tmp_path.joinpath(name)
    original.save(destination)
    decoded = PngImage.load(str(destination))
    assert decoded.header.to_chunk().data == original.header.to_chunk().data
    assert decoded.bitmap == original.bitmap
    assert decoded.palette == original.palette
    assert decoded.transparent_color == original.transparent_color
    assert decoded.palette_alpha == original.palette_alpha


@pytest.mark.parametrize('name', _BASE_NAMES)
def test_pngsuite_independent_adam7_pair(png_suite_dir: Path, name: str) -> None:
    plain = PngImage.load(png_suite_dir.joinpath(name))
    interlaced = PngImage.load(png_suite_dir.joinpath(name.replace('basn', 'basi')))
    assert plain.bitmap == interlaced.bitmap
    assert plain.palette == interlaced.palette


@pytest.mark.parametrize('suffix', ['0g08', '2c08'])
@pytest.mark.parametrize('kind', range(1, 5))
def test_pngsuite_independent_filter_pairs(png_suite_dir: Path, suffix: str, kind: int) -> None:
    plain = PngImage.load(png_suite_dir.joinpath(f'f00n{suffix}.png'))
    filtered = PngImage.load(png_suite_dir.joinpath(f'f0{kind}n{suffix}.png'))
    # Each fixture draws its own filter number in the center. Only compare
    # their common region; whole-image equality would be a false expectation.
    assert filtered.bitmap[:8] == plain.bitmap[:8]


@pytest.mark.parametrize('name', _BASE_NAMES)
@pytest.mark.parametrize('kind', list(PngFilterType))
@pytest.mark.parametrize('interlace', list(PngInterlaceMethod))
@pytest.mark.parametrize('dimensions', [(1, 1), (2, 3), (9, 5)])
def test_encoding_formats_filters_and_small_passes(
    png_suite_dir: Path,
    name: str,
    kind: PngFilterType,
    interlace: PngInterlaceMethod,
    dimensions: tuple[int, int],
) -> None:
    source = PngImage.load(png_suite_dir.joinpath(name))
    width, height = dimensions
    source.header.dimensions = dimensions
    source.header.interlace_method = interlace
    source.bitmap = [row[: width * source.header.channels] for row in source.bitmap[:height]]
    encoded = source.dump_to_bytes(filter_type=kind, idat_chunk_size=7)
    restored = PngImage.parse(encoded)
    assert restored.bitmap == source.bitmap
    assert restored.palette == source.palette
    assert restored.header.interlace_method == interlace


def test_create_edit_and_file_api(tmp_path: Path) -> None:
    image = PngImage(PngHeader((2, 1)), [[255, 0, 0, 255, 0, 255, 0, 128]])
    image.validate()
    stream = BytesIO()
    image.dump(stream)
    assert not stream.closed
    stream.seek(0)
    loaded = PngImage.parse(stream)
    loaded.bitmap[0][0:4] = [0, 0, 255, 255]
    destination = tmp_path.joinpath('created.png')
    loaded.save(destination)
    assert PngImage.load(destination).bitmap == [[0, 0, 255, 255, 0, 255, 0, 128]]


def test_decode_and_encode_are_independent_of_document(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn3p08.png'))
    original_bytes = document.dump_to_bytes()
    image = PngImage.from_document(document)
    image.bitmap[0][0] = (image.bitmap[0][0] + 1) % len(image.palette)
    assert document.dump_to_bytes() == original_bytes
    encoded = image.to_document()
    image.palette[0] = (255, 255, 255)
    assert encoded.find_chunks(b'PLTE')[0].data != bytes(sample for color in image.palette for sample in color)


def _replace_idat(document: PngDocument, data: bytes) -> PngDocument:
    position = next(index for index, chunk in enumerate(document.chunks) if chunk.type == b'IDAT')
    document.chunks = [chunk for chunk in document.chunks if chunk.type != b'IDAT']
    document.chunks.insert(position, PngChunk(b'IDAT', data))
    return document


@pytest.mark.parametrize('damage', ['truncated', 'bad_adler', 'extra', 'short', 'filter', 'dictionary', 'two_streams'])
def test_bad_image_data(png_suite_dir: Path, damage: str) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn0g08.png'))
    compressed = b''.join(chunk.data for chunk in document.find_chunks(b'IDAT'))
    raw = zlib.decompress(compressed)
    if damage == 'truncated':
        data = compressed[:-1]
    elif damage == 'bad_adler':
        data = compressed[:-1] + bytes([compressed[-1] ^ 1])
    elif damage == 'extra':
        data = zlib.compress(raw + b'\x00')
    elif damage == 'short':
        data = zlib.compress(raw[:-1])
    elif damage == 'filter':
        data = zlib.compress(b'\x05' + raw[1:])
    elif damage == 'dictionary':
        compressor = zlib.compressobj(zdict=b'forbidden preset dictionary')
        data = compressor.compress(raw) + compressor.flush()
    else:
        # IDAT is one zlib stream, not a concatenation of independent streams.
        data = zlib.compress(raw[:10]) + zlib.compress(raw[10:])
    with pytest.raises(PngParseError):
        PngImage.from_document(_replace_idat(document, data))


def test_idat_boundaries_and_allowed_trailing_bytes(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn2c16.png'))
    original = PngImage.from_document(document)
    compressed = b''.join(chunk.data for chunk in document.find_chunks(b'IDAT')) + b'\0\0'
    document = _replace_idat(document, compressed)
    position = next(index for index, chunk in enumerate(document.chunks) if chunk.type == b'IDAT')
    document.chunks[position : position + 1] = (
        [PngChunk(b'IDAT')] + [PngChunk(b'IDAT', bytes([value])) for value in compressed] + [PngChunk(b'IDAT')]
    )
    assert PngImage.parse(document.dump_to_bytes()).bitmap == original.bitmap


def test_huge_ihdr_rejected_before_bitmap_allocation(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn0g08.png'))
    header = PngHeader.from_chunk(document.chunks[0])
    header.dimensions = (0x7FFFFFFF, 0x7FFFFFFF)
    document.chunks[0] = header.to_chunk()
    with pytest.raises(PngParseError, match='scanline bytes'):
        PngImage.from_document(document)


def test_low_bit_padding_is_not_a_pixel(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('s01n3p01.png'))
    compressed = b''.join(chunk.data for chunk in document.find_chunks(b'IDAT'))
    raw = zlib.decompress(compressed)
    assert raw[0] == 0
    original = PngImage.from_document(document)
    changed = bytes([0, raw[1] | 0x7F])
    decoded = PngImage.from_document(_replace_idat(document, zlib.compress(changed)))
    assert decoded.bitmap == original.bitmap


def test_transparent_sample_uses_all_16_bits(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn0g16.png'))
    document.chunks.insert(-2, PngChunk(b'tRNS', pack('>H', 0x1234)))
    image = PngImage.from_document(document)
    assert image.transparent_color == (0x1234,)
    assert PngImage.parse(image.dump_to_bytes()).transparent_color == (0x1234,)


def test_exact_16_bit_sample_byte_order(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn2c16.png'))
    header = PngHeader.from_chunk(document.chunks[0])
    header.dimensions = (1, 1)
    document.chunks[0] = header.to_chunk()
    raw = b'\x00\x12\x34\xab\xcd\x00\x01'
    image = PngImage.from_document(_replace_idat(document, zlib.compress(raw)))
    assert image.bitmap == [[0x1234, 0xABCD, 1]]
    encoded = image.to_document(filter_type=PngFilterType.NONE)
    assert zlib.decompress(b''.join(chunk.data for chunk in encoded.find_chunks(b'IDAT'))) == raw


@pytest.mark.parametrize(
    ('depth', 'samples', 'packed'),
    [
        (1, [1, 0, 1, 1, 0, 0, 0, 1, 1], b'\xb1\x80'),
        (2, [0, 1, 2, 3, 1], b'\x1b\x40'),
        (4, [1, 15, 8], b'\x1f\x80'),
    ],
)
def test_exact_subbyte_sample_packing(depth: int, samples: list[int], packed: bytes) -> None:
    image = PngImage(PngHeader((len(samples), 1), depth, PngColorType.GRAYSCALE), [samples])
    document = image.to_document(filter_type=PngFilterType.NONE)
    data = zlib.decompress(b''.join(chunk.data for chunk in document.find_chunks(b'IDAT')))
    assert data == b'\x00' + packed
    assert PngImage.from_document(document).bitmap == [samples]


def test_low_depth_transparency_masks_unused_high_bits(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn0g04.png'))
    document.chunks.insert(-2, PngChunk(b'tRNS', pack('>H', 0xFFF3)))
    image = PngImage.from_document(document)
    assert image.transparent_color == (3,)
    assert image.to_document().find_chunks(b'tRNS')[0].data == b'\0\3'


def test_invalid_palette_index_recovers_as_opaque_black(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn3p01.png'))
    document.find_chunks(b'PLTE')[0].data = b'\xff\xff\xff'  # Only index 0 is now defined.
    document.chunks.insert(-2, PngChunk(b'tRNS', b'\x00'))
    image = PngImage.from_document(document)
    assert image.palette == [(255, 255, 255), (0, 0, 0)]
    assert image.palette_alpha == [0, 255]
    image.validate()
    restored = PngImage.parse(image.dump_to_bytes())
    assert restored.palette == image.palette
    assert restored.palette_alpha == image.palette_alpha


def test_ancillary_copy_policy_and_positions(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))
    document.chunks.insert(1, PngChunk(b'vpAg', b'before'))
    document.chunks.insert(-1, PngChunk(b'vpAg', b'after'))
    document.chunks.insert(-1, PngChunk(b'vpAG', b'unsafe'))
    image = deepcopy(PngImage.from_document(document))
    encoded = image.to_document()
    kinds = [chunk.type for chunk in encoded.chunks]
    positions = [index for index, chunk in enumerate(encoded.chunks) if chunk.type == b'vpAg']
    assert positions[0] < kinds.index(b'IDAT') < positions[1]
    assert not encoded.find_chunks(b'vpAG')
    assert encoded.find_chunks(b'gAMA')
    assert any(chunk.type == b'vpAG' for chunk in image.ancillary_chunks)


def test_new_image_metadata_is_explicit() -> None:
    image = PngImage(
        PngHeader((1, 1), color_type=PngColorType.INDEXED_COLOR, bit_depth=1),
        [[0]],
        palette=[(0, 0, 0)],
        ancillary_chunks=[
            PngChunk(b'bKGD', b'\0'),
            PngChunk(b'gAMA', pack('>I', 45455)),
        ],
    )
    encoded = image.to_document()
    kinds = [chunk.type for chunk in encoded.chunks]
    assert kinds.index(b'gAMA') < kinds.index(b'PLTE') < kinds.index(b'bKGD') < kinds.index(b'IDAT')


def test_incomplete_apng_is_rejected(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))
    document.chunks.insert(1, PngChunk(b'acTL', pack('>II', 1, 0)))
    with pytest.raises(PngValidationError, match='frames'):
        PngImage.from_document(document)
    image = PngImage(PngHeader((1, 1)), [[0] * 4], animation=PngAnimation())
    with pytest.raises(PngValidationError, match='frames'):
        image.to_document()


@pytest.mark.parametrize(
    ('options', 'field'),
    [
        ({'filter_type': 5}, 'filter type'),
        ({'filter_type': True}, 'filter type'),
        ({'compression_level': 10}, 'compression level'),
        ({'idat_chunk_size': 0}, 'chunk size'),
    ],
)
def test_invalid_encoder_options(options, field: str) -> None:
    image = PngImage(PngHeader((1, 1)), [[0] * 4])
    with pytest.raises(PngValidationError, match=field):
        image.dump_to_bytes(**options)


def test_failed_image_save_does_not_truncate(tmp_path: Path) -> None:
    path = tmp_path.joinpath('preserved.png')
    image = PngImage(PngHeader((1, 1)), [[0] * 4])
    image.save(path)
    before = path.read_bytes()
    image.bitmap.clear()
    with pytest.raises(PngValidationError):
        image.save(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ('kind', 'scanlines'),
    [
        (PngFilterType.NONE, bytes([0, 10, 20, 30, 0, 30, 20, 10])),
        (PngFilterType.SUB, bytes([1, 10, 10, 10, 1, 30, 246, 246])),
        (PngFilterType.UP, bytes([2, 10, 20, 30, 2, 20, 0, 236])),
        (PngFilterType.AVERAGE, bytes([3, 10, 15, 20, 3, 25, 251, 241])),
        (PngFilterType.PAETH, bytes([4, 10, 10, 10, 4, 20, 246, 236])),
    ],
)
def test_fixed_filter_scanlines(kind: PngFilterType, scanlines: bytes) -> None:
    header = PngHeader((3, 2), color_type=PngColorType.GRAYSCALE)
    document = PngDocument(
        [
            header.to_chunk(),
            PngChunk(b'IDAT', zlib.compress(scanlines)),
            PngChunk(b'IEND'),
        ]
    )
    image = PngImage.from_document(document)
    assert image.bitmap == [[10, 20, 30], [30, 20, 10]]
    encoded = image.to_document(filter_type=kind)
    assert zlib.decompress(b''.join(chunk.data for chunk in encoded.find_chunks(b'IDAT'))) == scanlines


@pytest.mark.parametrize('sample', [True, 1.0, -1, 256])
@pytest.mark.parametrize('in_frame', [False, True])
def test_loaded_samples_are_revalidated_after_editing(sample, in_frame: bool, tmp_path: Path) -> None:
    image = PngImage(
        PngHeader((1, 1)),
        [[10, 20, 30, 255]],
        animation=PngAnimation(frames=[PngFrame(PngFrameControl((1, 1)), [[40, 50, 60, 128]])]),
    )
    loaded = PngImage.parse(image.dump_to_bytes())
    bitmap = loaded.animation.frames[0].bitmap if in_frame else loaded.bitmap
    bitmap[0][0] = sample
    with pytest.raises(PngValidationError, match='pixel sample'):
        loaded.validate()
    stream = BytesIO(b'preserved')
    with pytest.raises(PngValidationError, match='pixel sample'):
        loaded.dump(stream)
    assert stream.getvalue() == b'preserved'
    destination = tmp_path.joinpath('preserved.png')
    destination.write_bytes(b'preserved')
    with pytest.raises(PngValidationError, match='pixel sample'):
        loaded.save(destination)
    assert destination.read_bytes() == b'preserved'


def test_from_document_revalidates_previously_loaded_document(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn6a08.png'))
    PngImage.from_document(document)
    document.chunks.insert(-1, document.chunks[0])
    with pytest.raises(PngValidationError, match='duplicate'):
        PngImage.from_document(document)


@pytest.mark.parametrize('from_document', [False, True])
def test_image_output_rejects_reserved_chunks_before_writing(from_document: bool, tmp_path: Path) -> None:
    image = PngImage(PngHeader((1, 1)), [[10, 20, 30, 255]])
    reserved = PngChunk(b'vpag', b'future')
    if from_document:
        model = image.to_document()
        # A document returned for inspection must be checked again after edits.
        model.chunks.insert(-1, reserved)
    else:
        image.ancillary_chunks.append(reserved)
        model = image
        assert image.to_document().find_chunks(b'vpag')[0].data == b'future'
    stream = BytesIO(b'preserved')
    with pytest.raises(PngValidationError, match='reserved'):
        model.dump(stream)
    assert stream.getvalue() == b'preserved'
    destination = tmp_path.joinpath('preserved.png')
    destination.write_bytes(b'preserved')
    with pytest.raises(PngValidationError, match='reserved'):
        model.save(destination)
    assert destination.read_bytes() == b'preserved'
    with pytest.raises(PngValidationError, match='reserved'):
        model.dump_to_bytes()
