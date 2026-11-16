from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest

from png import (
    PngCalibration,
    PngCalibrationEquation,
    PngChunk,
    PngDocument,
    PngGifApplication,
    PngGifGraphicControl,
    PngImage,
    PngMetadata,
    PngOffset,
    PngOffsetUnit,
    PngParseError,
    PngPhysicalScale,
    PngScaleUnit,
    PngStereo,
    PngStereoMode,
    PngValidationError,
)


VECTORS = [
    (PngOffset((-2147483648, 2147483647), PngOffsetUnit.MICROMETRE), bytes.fromhex('800000007fffffff01')),
    (
        PngCalibration('SI', -1, 255, parameters=['-1.25', '+2E3']),
        b'SI\0' + bytes.fromhex('ffffffff000000ff0002') + b'\0-1.25\0+2E3',
    ),
    (
        PngCalibration('Reverse', 10, -10, PngCalibrationEquation.HYPERBOLIC, ' K  ', ['0', '1e-30', '280', '32767']),
        b'Reverse\0' + bytes.fromhex('0000000afffffff60304') + b' K  \x000\x001e-30\x00280\x0032767',
    ),
    (PngPhysicalScale('+1.25e-9', '.5', PngScaleUnit.RADIAN), b'\x02+1.25e-9\0.5'),
    (PngGifGraphicControl(3, 1, 258), bytes.fromhex('03010102')),
    (PngGifApplication('NETSCAPE', b'2.0', bytes.fromhex('010000')), b'NETSCAPE2.0\x01\0\0'),
    (PngStereo(PngStereoMode.DIVERGING_FUSE), b'\x01'),
]


@pytest.mark.parametrize(('metadata', 'payload'), VECTORS)
def test_specification_payload_vectors(metadata: PngMetadata, payload: bytes) -> None:
    assert metadata.to_chunk().data == payload
    restored = type(metadata).from_chunk(PngChunk(metadata.type, payload))
    assert restored.to_chunk().data == payload
    restored.validate()
    with pytest.raises(PngValidationError):
        type(metadata).from_chunk(PngChunk(b'tEXt', payload))


def test_public_fields_and_derived_values() -> None:
    offset = PngOffset()
    offset.position = (-2, 3)
    offset.x = -4
    assert offset.position == (-4, 3)
    assert PngGifGraphicControl(delay_time=25).delay == Fraction(1, 4)
    parameters = ['0', '1']
    calibration = PngCalibration('SI', 0, 255, parameters=parameters)
    assert calibration.parameters is parameters
    assert calibration.num_parameters == 2
    clone = deepcopy(calibration)
    clone.parameters[0] = '2'
    assert calibration.parameters == ['0', '1']
    assert PngCalibration('A', 0, 1).parameters is not PngCalibration('A', 0, 1).parameters


@pytest.mark.parametrize(('equation', 'count'), [(0, 2), (1, 3), (2, 3), (3, 4)])
def test_calibration_equation_counts(equation: int, count: int) -> None:
    calibration = PngCalibration('Calibration', 2147483647, -2147483648, equation, ' µm  ', ['1.'] * count)
    restored = PngCalibration.from_chunk(calibration.to_chunk())
    assert restored.original_zero > restored.original_max
    assert restored.equation_type == PngCalibrationEquation(equation)
    assert restored.unit_name == ' µm  '
    restored.parameters.pop()
    with pytest.raises(PngValidationError, match='parameter count'):
        restored.validate()


@pytest.mark.parametrize('number', ['0', '-0', '+0.', '.0', '1', '-.5', '+123.', '1.e+2', '01.2300E-4000'])
def test_calibration_preserves_decimal_spelling(number: str) -> None:
    calibration = PngCalibration('Test', 0, 1, parameters=[number, number])
    assert PngCalibration.from_chunk(calibration.to_chunk()).parameters == [number, number]


@pytest.mark.parametrize('number', ['1', '.5', '+.0001', '01.2300E-4000', '1e' + '9' * 1000])
def test_physical_scale_preserves_precision_and_unbounded_exponents(number: str) -> None:
    scale = PngPhysicalScale(number, number)
    restored = PngPhysicalScale.from_chunk(scale.to_chunk())
    assert (restored.pixel_width, restored.pixel_height) == (number, number)


@pytest.mark.parametrize(
    'number',
    ['', '.', '+', '1e', '1e+', '1 2', ' 1', '1\n', 'NaN', 'inf', '1_000', '1,2', '1f', '\u0661', '0x10', '1\0'],
)
def test_invalid_decimal_grammar(number: str) -> None:
    with pytest.raises(PngValidationError):
        PngCalibration('Test', 0, 1, parameters=[number, '0']).validate()
    with pytest.raises(PngValidationError):
        PngPhysicalScale(number, '1').validate()


@pytest.mark.parametrize('number', ['0', '-0', '+0.', '.0', '0.0e9999', '-1', '-1e-9999'])
def test_physical_scale_requires_positive_values(number: str) -> None:
    with pytest.raises(PngValidationError, match='greater than zero'):
        PngPhysicalScale('1', number).validate()


@pytest.mark.parametrize(
    ('cls', 'kind', 'payload'),
    [
        (PngOffset, b'oFFs', bytes(8)),
        (PngOffset, b'oFFs', bytes(10)),
        (PngOffset, b'oFFs', bytes(8) + b'\x02'),
        (PngCalibration, b'pCAL', b'Name'),
        (PngCalibration, b'pCAL', b'Name\0' + bytes(9)),
        (PngCalibration, b'pCAL', b'N\0' + bytes.fromhex('00000000000000010002') + b'\x000'),
        (PngCalibration, b'pCAL', b'N\0' + bytes.fromhex('00000000000000010002') + b'\x000\x001\0'),
        (PngCalibration, b'pCAL', b'N\0' + bytes.fromhex('00000000000000010402') + b'\x000\x001'),
        (PngPhysicalScale, b'sCAL', b''),
        (PngPhysicalScale, b'sCAL', b'\x011'),
        (PngPhysicalScale, b'sCAL', b'\x001\x001'),
        (PngPhysicalScale, b'sCAL', b'\x011\x001\0'),
        (PngPhysicalScale, b'sCAL', b'\x01\xff\x001'),
        (PngGifGraphicControl, b'gIFg', bytes(3)),
        (PngGifGraphicControl, b'gIFg', b'\x08' + bytes(3)),
        (PngGifGraphicControl, b'gIFg', b'\x00\x02\0\0'),
        (PngGifApplication, b'gIFx', bytes(10)),
        (PngGifApplication, b'gIFx', b'\x7f' + b'A' * 10),
        (PngGifApplication, b'gIFx', b'\xff' + b'A' * 10),
        (PngStereo, b'sTER', b''),
        (PngStereo, b'sTER', b'\0\0'),
        (PngStereo, b'sTER', b'\x02'),
    ],
)
def test_invalid_wire_payloads(cls, kind: bytes, payload: bytes) -> None:
    with pytest.raises(PngValidationError):
        cls.from_chunk(PngChunk(kind, payload))


@pytest.mark.parametrize(
    'metadata',
    [
        PngOffset((-2147483649, 0)),
        PngOffset((0, 2147483648)),
        PngOffset(unit=True),
        PngCalibration('Bad  Name', 0, 1, parameters=['0', '1']),
        PngCalibration('Test', 1, 1, parameters=['0', '1']),
        PngCalibration('Test', 0, 1, unit_name='\x7f', parameters=['0', '1']),
        PngCalibration('Test', 0, 1, unit_name='\xa0', parameters=['0', '1']),
        PngCalibration('Test', 0, 1, parameters=[1, '1']),
        PngPhysicalScale('1', '1', 3),
        PngPhysicalScale(1, '1'),
        PngGifGraphicControl(-1),
        PngGifGraphicControl(delay_time=65536),
        PngGifGraphicControl(user_input_flag=True),
        PngGifApplication('SHORT', b'123'),
        PngGifApplication('LongName', b'12'),
        PngGifApplication('LongName', bytearray(b'123')),
        PngGifApplication('LongName', b'123', 'text'),
        PngStereo(2),
    ],
)
def test_invalid_model_fields(metadata: PngMetadata) -> None:
    with pytest.raises(PngValidationError):
        metadata.validate()


@pytest.mark.parametrize('disposal', range(8))
def test_gif_reserved_disposal_values_survive_as_opaque_compatibility_data(disposal: int) -> None:
    item = PngGifGraphicControl(disposal, 1, 65535)
    assert PngGifGraphicControl.from_chunk(item.to_chunk()).disposal_method == disposal
    application = PngGifApplication('APP NAME', b'\0\xff\x80', bytes(range(256)))
    assert PngGifApplication.from_chunk(application.to_chunk()).data == bytes(range(256))


@pytest.mark.parametrize('subimage_width', range(1, 33))
def test_stereo_alignment_and_dimensions(subimage_width: int) -> None:
    padding = (-subimage_width) % 8
    width = 2 * subimage_width + padding
    assert PngStereo().layout(width) == (subimage_width, padding)
    assert (subimage_width + padding) % 8 == 0


@pytest.mark.parametrize('width', [1, 2, 7, 8, 17, 24, 0, -1, True])
def test_stereo_rejects_impossible_canvas_width(width: int) -> None:
    with pytest.raises(PngValidationError):
        PngStereo().layout(width)


@pytest.mark.parametrize(('item', 'payload'), VECTORS)
def test_extensions_survive_pixel_edits_on_official_image(
    png_suite_dir: Path,
    item: PngMetadata,
    payload: bytes,
) -> None:
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(deepcopy(item))
    document = image.to_document(idat_chunk_size=1)
    restored = PngImage.from_document(document)
    assert restored.ancillary_chunks == []
    (actual,) = restored.find_metadata(item.type)
    assert isinstance(actual, type(item))
    assert actual.to_chunk().data == payload
    restored.bitmap[0][0] ^= 255
    output = PngImage.parse(restored.dump_to_bytes())
    assert output.bitmap == restored.bitmap
    assert output.find_metadata(item.type)[0].to_chunk().data == payload
    assert output.animation is None


@pytest.mark.parametrize(
    'item', [PngOffset(), PngCalibration('Test', 0, 1, parameters=['0', '1']), PngPhysicalScale('1', '2'), PngStereo()]
)
def test_singletons_and_ordering(png_suite_dir: Path, item: PngMetadata) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))
    document.chunks.insert(-1, item.to_chunk())
    with pytest.raises(PngValidationError, match='precede IDAT'):
        document.validate()
    document.chunks.pop(-2)
    document.chunks[1:1] = [item.to_chunk(), item.to_chunk()]
    with pytest.raises(PngValidationError, match='duplicate'):
        document.validate()
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.extend([item, deepcopy(item)])
    with pytest.raises(PngValidationError, match='duplicate'):
        image.validate()


def test_gif_repeated_metadata_keeps_its_side_of_idat(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))
    items = [
        PngGifGraphicControl(1, 0, 1),
        PngGifApplication('NETSCAPE', b'2.0'),
        PngGifGraphicControl(2, 1, 2),
        PngGifApplication('NETSCAPE', b'2.0', b'abc'),
    ]
    document.chunks[1:1] = [item.to_chunk() for item in items[:2]]
    document.chunks[-1:-1] = [item.to_chunk() for item in items[2:]]
    restored = PngImage.from_document(PngDocument.parse(document.dump_to_bytes())).to_document()
    kinds = [chunk.type for chunk in restored.chunks]
    first_data = kinds.index(b'IDAT')
    assert [chunk.data for chunk in restored.chunks[:first_data] if chunk.type in (b'gIFg', b'gIFx')] == [
        item.to_chunk().data for item in items[:2]
    ]
    assert [chunk.data for chunk in restored.chunks[first_data:] if chunk.type in (b'gIFg', b'gIFx')] == [
        item.to_chunk().data for item in items[2:]
    ]


def test_stereo_checks_parent_dimensions(png_suite_dir: Path) -> None:
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(PngStereo())
    image.bitmap = [row[:24] for row in image.bitmap]
    image.header.width = 8
    with pytest.raises(PngValidationError, match='sTER image width'):
        image.validate()
    document = PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))
    document.chunks[0] = image.header.to_chunk()
    document.chunks.insert(1, PngStereo().to_chunk())
    with pytest.raises(PngValidationError, match='sTER image width'):
        document.validate()
    # Chunk serialization alone intentionally does not check image context.
    data = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    with pytest.raises(PngParseError, match='sTER image width'):
        PngDocument.parse(data)


def test_other_extensions_keep_unknown_chunk_editing_rules(png_suite_dir: Path) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))
    for kind in (b'gIFt', b'fRAc', b'dSIG', b'iDOT'):
        document.chunks.insert(-1, PngChunk(kind, b'opaque'))
    original = PngDocument.parse(document.dump_to_bytes())
    assert original.dump_to_bytes() == document.dump_to_bytes()
    image = PngImage.from_document(original)
    output = PngDocument.parse(image.dump_to_bytes())
    assert output.find_chunks(b'gIFt') and output.find_chunks(b'fRAc')
    assert not output.find_chunks(b'dSIG') and not output.find_chunks(b'iDOT')
