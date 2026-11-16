from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from png import (
    PngAnimation,
    PngBackground,
    PngChunk,
    PngColorType,
    PngDocument,
    PngFrame,
    PngFrameControl,
    PngHeader,
    PngHistogram,
    PngImage,
    PngSignificantBits,
    PngSuggestedPalette,
    PngSuggestedPaletteEntry,
    PngValidationError,
)


@pytest.mark.parametrize(
    ('metadata', 'expected'),
    [
        (PngBackground(palette_index=2), b'\x02'),
        (PngBackground(color=(0x1234,)), b'\x12\x34'),
        (PngBackground(color=(0x1234, 0xABCD, 0)), bytes.fromhex('1234abcd0000')),
        (PngHistogram([0, 1, 65535]), bytes.fromhex('00000001ffff')),
        (PngSignificantBits((5, 6, 5)), b'\x05\x06\x05'),
        (
            PngSuggestedPalette('Alt', 8, [PngSuggestedPaletteEntry((1, 2, 3, 255), 258)]),
            b'Alt\0\x08' + bytes.fromhex('010203ff0102'),
        ),
        (
            PngSuggestedPalette('Alt', 16, [PngSuggestedPaletteEntry((0x1234, 0x5678, 0x9ABC, 65535), 65535)]),
            b'Alt\0\x10' + bytes.fromhex('123456789abcffffffff'),
        ),
    ],
)
def test_reference_payloads(metadata, expected: bytes) -> None:
    assert metadata.to_chunk().data == expected
    restored = type(metadata).from_chunk(PngChunk(metadata.type, expected))
    assert restored.to_chunk().data == expected


@pytest.mark.parametrize(
    ('name', 'kind', 'expected_type'),
    [
        ('bgyn6a16.png', b'bKGD', PngBackground),
        ('ch1n3p04.png', b'hIST', PngHistogram),
        ('ch2n3p08.png', b'hIST', PngHistogram),
        ('cs3n2c16.png', b'sBIT', PngSignificantBits),
        ('cs5n3p08.png', b'sBIT', PngSignificantBits),
        ('ps1n0g08.png', b'sPLT', PngSuggestedPalette),
        ('ps1n2c16.png', b'sPLT', PngSuggestedPalette),
        ('ps2n0g08.png', b'sPLT', PngSuggestedPalette),
        ('ps2n2c16.png', b'sPLT', PngSuggestedPalette),
    ],
)
def test_official_typed_payloads(png_suite_dir: Path, name: str, kind: bytes, expected_type) -> None:
    document = PngDocument.load(png_suite_dir.joinpath(name))
    image = PngImage.from_document(document)
    (item,) = image.find_metadata(kind)
    assert isinstance(item, expected_type)
    assert item.to_chunk().data == document.find_chunks(kind)[0].data
    restored = PngImage.parse(image.dump_to_bytes())
    assert restored.find_metadata(kind)[0].to_chunk().data == item.to_chunk().data


@pytest.mark.parametrize(
    ('name', 'background'),
    [
        ('basn0g04.png', PngBackground(color=(15,))),
        ('basn4a08.png', PngBackground(color=(255,))),
        ('basn2c16.png', PngBackground(color=(0x1234, 0xABCD, 65535))),
        ('basn6a08.png', PngBackground(color=(1, 2, 3))),
        ('basn3p01.png', PngBackground(palette_index=1)),
    ],
)
def test_background_matches_color_type(png_suite_dir: Path, name: str, background: PngBackground) -> None:
    image = PngImage.load(png_suite_dir.joinpath(name))
    image.metadata.append(background)
    image.validate()
    restored = PngImage.parse(image.dump_to_bytes())
    assert restored.find_metadata(b'bKGD')[0].to_chunk().data == background.to_chunk().data


@pytest.mark.parametrize(
    ('name', 'background'),
    [
        ('basn0g04.png', PngBackground(color=(16,))),
        ('basn0g04.png', PngBackground(color=(1, 2, 3))),
        ('basn2c08.png', PngBackground(color=(1,))),
        ('basn2c08.png', PngBackground(palette_index=0)),
        ('basn3p01.png', PngBackground(palette_index=2)),
        ('basn3p01.png', PngBackground(color=(0, 0, 0))),
    ],
)
def test_background_context_rejects_inconsistent_values(png_suite_dir: Path, name, background) -> None:
    image = PngImage.load(png_suite_dir.joinpath(name))
    image.metadata.append(background)
    with pytest.raises(PngValidationError, match='bKGD'):
        image.validate()


def test_background_read_masks_unused_high_bits(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn0g04.png'))
    document.chunks.insert(-2, PngChunk(b'bKGD', b'\xff\xf3'))
    # Raw access preserves the original bytes; the pixel model normalizes samples.
    assert PngDocument.parse(document.dump_to_bytes()).find_chunks(b'bKGD')[0].data == b'\xff\xf3'
    image = PngImage.from_document(document)
    assert image.find_metadata(b'bKGD')[0].color == (3,)
    assert image.to_document().find_chunks(b'bKGD')[0].data == b'\0\3'


def test_background_is_not_implicitly_composited() -> None:
    image = PngImage(PngHeader((1, 1)), [[255, 0, 0, 0]], metadata=[PngBackground(color=(255, 255, 255))])
    snapshot = next(image.render_frames()).image
    assert snapshot.bitmap == [[255, 0, 0, 0]]


@pytest.mark.parametrize(
    ('name', 'bits'),
    [
        ('basn0g04.png', (4,)),
        ('basn2c16.png', (12, 13, 14)),
        ('basn3p01.png', (8, 8, 8)),
        ('basn4a08.png', (8, 7)),
        ('basn6a16.png', (16, 15, 14, 13)),
    ],
)
def test_significant_bits_context(png_suite_dir: Path, name: str, bits: tuple[int, ...]) -> None:
    image = PngImage.load(png_suite_dir.joinpath(name))
    image.metadata = [item for item in image.metadata if item.type != b'sBIT']
    image.metadata.append(PngSignificantBits(bits))
    image.validate()
    assert PngImage.parse(image.dump_to_bytes()).find_metadata(b'sBIT')[0].bits == bits


@pytest.mark.parametrize(
    ('name', 'bits'),
    [
        ('basn0g04.png', (5,)),
        ('basn2c08.png', (8, 8)),
        ('basn3p01.png', (9, 8, 8)),
        ('basn4a08.png', (8,)),
        ('basn6a16.png', (16, 16, 16)),
    ],
)
def test_significant_bits_rejects_invalid_context(png_suite_dir: Path, name: str, bits: tuple[int, ...]) -> None:
    image = PngImage.load(png_suite_dir.joinpath(name))
    image.metadata = [item for item in image.metadata if item.type != b'sBIT']
    image.metadata.append(PngSignificantBits(bits))
    with pytest.raises(PngValidationError, match='sBIT'):
        image.validate()


def _indexed() -> PngImage:
    return PngImage(
        PngHeader((3, 1), bit_depth=2, color_type=PngColorType.INDEXED_COLOR),
        [[0, 0, 1]],
        palette=[(0, 0, 0), (255, 0, 0), (0, 255, 0)],
    )


def test_recalculate_histogram_after_pixel_and_palette_edits() -> None:
    image = _indexed()
    histogram = image.recalculate_histogram()
    assert histogram.frequencies == [2, 1, 0]
    original_list = histogram.frequencies
    image.bitmap[0][2] = 2
    with pytest.raises(PngValidationError, match='nonzero'):
        image.validate()
    assert image.recalculate_histogram() is histogram
    assert histogram.frequencies is original_list
    assert histogram.frequencies == [2, 0, 1]
    image.palette.append((0, 0, 255))
    with pytest.raises(PngValidationError, match='PLTE'):
        image.validate()
    image.recalculate_histogram()
    assert histogram.frequencies == [2, 0, 1, 0]
    image.validate()
    assert PngImage.parse(image.dump_to_bytes()).find_metadata(b'hIST')[0].frequencies == [2, 0, 1, 0]


def test_histogram_scaling_preserves_rare_used_indices() -> None:
    image = _indexed()
    image.header.dimensions = (65538, 1)
    image.bitmap = [[0] * 65536 + [1, 2]]
    assert image.recalculate_histogram().frequencies == [65535, 1, 1]
    image.validate()


def test_histogram_includes_static_fallback_and_local_frames() -> None:
    image = _indexed()
    image.animation = PngAnimation(frames=[PngFrame(PngFrameControl((1, 1)), [[2]])])
    image.metadata.append(PngHistogram([2, 1, 0]))
    with pytest.raises(PngValidationError, match='nonzero'):
        image.validate()
    assert image.recalculate_histogram().frequencies == [2, 1, 1]
    image.validate()


def test_recalculate_raw_histogram_replaces_it_with_structured_data() -> None:
    image = _indexed()
    image.ancillary_chunks.append(PngHistogram([1, 1, 1]).to_chunk())
    histogram = image.recalculate_histogram()
    assert histogram.frequencies == [2, 1, 0]
    assert not image.ancillary_chunks
    assert image.find_metadata(b'hIST') == [histogram]


def test_histogram_requires_palette_and_indexed_recalculation(png_suite_dir: Path) -> None:
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(PngHistogram([1]))
    with pytest.raises(PngValidationError, match='PLTE'):
        image.validate()
    with pytest.raises(PngValidationError, match='indexed'):
        image.recalculate_histogram()
    image.palette = [(0, 0, 0)]
    image.validate()  # A truecolor suggested palette may carry an approximate hIST.


def test_palette_index_repair_recalculates_histogram(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn3p01.png'))
    document.find_chunks(b'PLTE')[0].data = b'\xff\xff\xff'
    document.chunks.insert(-2, PngHistogram([1]).to_chunk())
    repaired = PngImage.from_document(document)
    assert len(repaired.palette) == 2
    expected = Counter(index for row in repaired.bitmap for index in row)
    assert repaired.find_metadata(b'hIST')[0].frequencies == [expected[0], expected[1]]
    repaired.validate()


def test_raw_critical_edit_omits_histogram_without_mutating_source(png_suite_dir: Path) -> None:
    path = png_suite_dir.joinpath('ch1n3p04.png')
    document = PngDocument.load(path)
    document.chunks.insert(-1, PngChunk(b'tEXt', b'Title\0Edited'))
    assert PngDocument.parse(document.dump_to_bytes()).find_chunks(b'hIST')
    index = next(index for index, chunk in enumerate(document.chunks) if chunk.type == b'IDAT')
    data = document.chunks[index].data
    document.chunks[index : index + 1] = [PngChunk(b'IDAT', data[:1]), PngChunk(b'IDAT', data[1:])]
    output = PngDocument.parse(document.dump_to_bytes())
    assert not output.find_chunks(b'hIST')
    assert document.find_chunks(b'hIST')
    assert PngImage.from_document(output).bitmap == PngImage.load(path).bitmap


def test_raw_critical_edit_accepts_explicit_new_histogram(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn3p01.png'))
    index = next(index for index, chunk in enumerate(document.chunks) if chunk.type == b'IDAT')
    data = document.chunks[index].data
    document.chunks[index : index + 1] = [PngChunk(b'IDAT', data[:1]), PngChunk(b'IDAT', data[1:])]
    document.chunks.insert(index, PngHistogram([1, 1]).to_chunk())
    assert PngImage.parse(document.dump_to_bytes()).find_metadata(b'hIST')[0].frequencies == [1, 1]


def test_raw_critical_edit_accepts_explicitly_revised_histogram(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('ch1n3p04.png'))
    histogram = document.find_chunks(b'hIST')[0]
    revised = PngHistogram.from_chunk(histogram)
    revised.frequencies = [(value % 65535) + 1 for value in revised.frequencies]
    histogram.data = revised.to_chunk().data
    index = next(index for index, chunk in enumerate(document.chunks) if chunk.type == b'IDAT')
    data = document.chunks[index].data
    document.chunks[index : index + 1] = [PngChunk(b'IDAT', data[:1]), PngChunk(b'IDAT', data[1:])]
    assert PngDocument.parse(document.dump_to_bytes()).find_chunks(b'hIST')[0].data == histogram.data


def test_suggested_palettes_are_independent_of_image_bit_depth() -> None:
    image = _indexed()
    image.metadata.extend(
        [
            PngSuggestedPalette('8 bit', 8, [PngSuggestedPaletteEntry((1, 2, 3, 255), 0)]),
            PngSuggestedPalette('16 bit', 16, [PngSuggestedPaletteEntry((1, 256, 65535, 32768), 0)]),
        ]
    )
    image.validate()
    output = PngImage.parse(image.dump_to_bytes())
    assert [item.sample_depth for item in output.find_metadata(b'sPLT')] == [8, 16]
    assert output.find_metadata(b'sPLT')[1].entries[0].color == (1, 256, 65535, 32768)
    assert output.palette == image.palette


def test_suggested_palette_names_order_and_mutable_entries() -> None:
    image = _indexed()
    palette = PngSuggestedPalette(
        'Alt',
        entries=[
            PngSuggestedPaletteEntry((255, 0, 0, 255), 10),
            PngSuggestedPaletteEntry((0, 255, 0, 128), 10),
            PngSuggestedPaletteEntry((0, 0, 0, 0), 0),
        ],
    )
    image.metadata.extend([palette, PngSuggestedPalette('alt', entries=[])])
    image.validate()
    clone = deepcopy(palette)
    clone.entries[0].color = (1, 2, 3, 4)
    assert palette.entries[0].red == 255
    image.metadata.append(PngSuggestedPalette('Alt'))
    with pytest.raises(PngValidationError, match='palette name'):
        image.validate()
    image.metadata.pop()
    palette.entries[1].frequency = 11
    with pytest.raises(PngValidationError, match='frequency order'):
        image.validate()


def test_suggested_palette_can_exceed_main_palette_limit() -> None:
    palette = PngSuggestedPalette(
        'More than 256', entries=[PngSuggestedPaletteEntry((0, 0, 0, 255)) for _ in range(257)]
    )
    encoded = palette.to_chunk()
    assert len(PngSuggestedPalette.from_chunk(encoded).entries) == 257


@pytest.mark.parametrize(
    ('cls', 'kind', 'payload'),
    [
        (PngBackground, b'bKGD', b''),
        (PngBackground, b'bKGD', bytes(3)),
        (PngHistogram, b'hIST', b''),
        (PngHistogram, b'hIST', b'\0'),
        (PngHistogram, b'hIST', bytes(514)),
        (PngSignificantBits, b'sBIT', b''),
        (PngSignificantBits, b'sBIT', b'\0'),
        (PngSignificantBits, b'sBIT', b'\x11'),
        (PngSignificantBits, b'sBIT', bytes([8] * 5)),
        (PngSuggestedPalette, b'sPLT', b'Alt'),
        (PngSuggestedPalette, b'sPLT', b'Alt\0'),
        (PngSuggestedPalette, b'sPLT', b'Alt\0\x01'),
        (PngSuggestedPalette, b'sPLT', b'Alt\0\x08\0'),
        (PngSuggestedPalette, b'sPLT', b'Alt\0\x10' + bytes(9)),
    ],
)
def test_malformed_contextual_metadata(cls, kind: bytes, payload: bytes) -> None:
    with pytest.raises(PngValidationError):
        cls.from_chunk(PngChunk(kind, payload))


@pytest.mark.parametrize(
    'metadata',
    [
        PngBackground(),
        PngBackground((1,), 0),
        PngBackground((-1,)),
        PngBackground((1, 2)),
        PngBackground(palette_index=256),
        PngHistogram([]),
        PngHistogram([-1]),
        PngHistogram([65536]),
        PngSignificantBits((0,)),
        PngSignificantBits((17,)),
        PngSuggestedPalette('Bad  Name'),
        PngSuggestedPalette('Alt', sample_depth=9),
        PngSuggestedPalette('Alt', entries=[PngSuggestedPaletteEntry((256, 0, 0, 255))]),
        PngSuggestedPalette('Alt', entries=[PngSuggestedPaletteEntry((0, 0, 0, 255), 65536)]),
    ],
)
def test_invalid_contextual_metadata_fields(metadata) -> None:
    with pytest.raises(PngValidationError):
        metadata.validate()
