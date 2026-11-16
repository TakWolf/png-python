"""ICC multi-process binary layout vectors and official-image integration."""

from io import BytesIO
from pathlib import Path
from struct import pack, unpack_from

import pytest

from png import PngDocument, PngIccProfile, PngImage, PngUnsupportedError, PngValidationError
from png._icc_mpet import validate_mpet, validate_mpet_context


def _element(kind: bytes, inputs: int, outputs: int, payload: bytes = b'') -> bytes:
    return kind + bytes(4) + pack('>HH', inputs, outputs) + payload


def _matrix(inputs: int = 3, outputs: int = 3) -> bytes:
    return _element(b'matf', inputs, outputs, pack('>f', 1) * (outputs * (inputs + 1)))


def _positions(items: list[bytes], start: int, storage_order: list[int] | None = None) -> bytes:
    offsets = {}
    data = bytearray()
    for index in storage_order if storage_order is not None else range(len(items)):
        value = items[index]
        if value not in offsets:
            offsets[value] = start + 8 * len(items) + len(data)
            data.extend(value)
            data.extend(bytes(-len(data) % 4))
    return b''.join(pack('>II', offsets[value], len(value)) for value in items) + bytes(data)


def _mpet(elements: list[bytes], storage_order: list[int] | None = None) -> bytes:
    (inputs,) = unpack_from('>H', elements[0], 8)
    (outputs,) = unpack_from('>H', elements[-1], 10)
    return b'mpet' + bytes(4) + pack('>HHI', inputs, outputs, len(elements)) + _positions(elements, 16, storage_order)


def _formula(function: int = 0) -> bytes:
    count = 4 if function == 0 else 5
    return b'parf' + bytes(4) + pack('>HH', function, 0) + pack('>f', 1) * count


def _sample(values: tuple[float, ...] = (0, 1)) -> bytes:
    return b'samf' + bytes(4) + pack('>I', len(values)) + pack('>' + 'f' * len(values), *values)


def _curve(segments: list[bytes], breakpoints: tuple[float, ...] = ()) -> bytes:
    return (
        b'curf'
        + bytes(4)
        + pack('>HH', len(segments), 0)
        + pack('>' + 'f' * len(breakpoints), *breakpoints)
        + b''.join(segments)
    )


def _curves(curves: list[bytes]) -> bytes:
    return _element(b'cvst', len(curves), len(curves), _positions(curves, 12))


def _clut(inputs: int = 3, outputs: int = 3) -> bytes:
    return _element(
        b'clut', inputs, outputs, bytes((2,)) * inputs + bytes(16 - inputs) + pack('>f', 0.5) * (2**inputs * outputs)
    )


def _u32(data: bytes, offset: int, value: int) -> bytes:
    return data[:offset] + pack('>I', value) + data[offset + 4 :]


@pytest.mark.parametrize(
    'elements',
    [
        [_matrix()],
        [_matrix(3, 20), _matrix(20, 1)],
        [_matrix(32, 32)],
        [_matrix(3, 0), _matrix(0, 3)],
        [_matrix(3, 0), _curves([]), _matrix(0, 3)],
        [_clut(1, 3), _matrix(3, 1)],
        [_element(b'bACS', 3, 3, b'abcd'), _matrix(), _element(b'eACS', 3, 3, b'abcd')],
    ],
)
def test_mpet_known_elements_and_channel_chains(elements: list[bytes]) -> None:
    validate_mpet(_mpet(elements))


def test_mpet_position_order_and_storage_order_are_independent() -> None:
    validate_mpet(_mpet([_matrix(3, 5), _matrix(5, 1)], [1, 0]))


def test_mpet_shared_elements_are_checked_once(monkeypatch) -> None:
    import png._icc_mpet as implementation

    original = implementation._validate_element
    calls = []

    def inspect(*args):
        calls.append(args[1])
        return original(*args)

    monkeypatch.setattr(implementation, '_validate_element', inspect)
    validate_mpet(_mpet([_matrix()] * 1000))
    assert len(calls) == 1


@pytest.mark.parametrize('damage', ['padding', 'channels', 'reserved'])
def test_unknown_elements_still_obey_common_storage_rules(damage: str) -> None:
    data = _mpet([_element(b'zzzz', 3, 3, b'A')])
    validate_mpet(data)
    if damage == 'padding':
        data = data[:-1] + b'X'
    elif damage == 'channels':
        data = data[:32] + bytes(2) + data[34:]
    else:
        data = _u32(data, 28, 1)
    with pytest.raises(PngValidationError, match='ICC'):
        validate_mpet(data)


@pytest.mark.parametrize(
    'damage',
    [
        'header',
        'reserved',
        'zero_inputs',
        'zero_outputs',
        'zero_count',
        'table_count',
        'offset_header',
        'offset_odd',
        'offset_outside',
        'first_stored',
        'short_element',
        'element_extent',
        'element_reserved',
        'element_zero',
        'input_chain',
        'output_chain',
        'matrix_count',
        'matrix_extra',
        'expansion_count',
        'expansion_channels',
    ],
)
def test_mpet_headers_positions_and_element_sizes(damage: str) -> None:
    data = _mpet([_matrix()])
    if damage == 'header':
        data = data[:15]
    elif damage == 'reserved':
        data = data[:4] + b'BAD!' + data[8:]
    elif damage == 'zero_inputs':
        data = data[:8] + bytes(2) + data[10:]
    elif damage == 'zero_outputs':
        data = data[:10] + bytes(2) + data[12:]
    elif damage == 'zero_count':
        data = _u32(data, 12, 0)
    elif damage == 'table_count':
        data = _u32(data, 12, 0xFFFFFFFF)
    elif damage == 'offset_header':
        data = _u32(data, 16, 12)
    elif damage == 'offset_odd':
        data = _u32(data, 16, 25)
    elif damage == 'offset_outside':
        data = _u32(data, 16, 0xFFFFFFFC)
    elif damage == 'first_stored':
        data = data[:24] + bytes(4) + data[24:]
        data = _u32(data, 16, 28)
    elif damage == 'short_element':
        data = _u32(data, 20, 8)
    elif damage == 'element_extent':
        data = _u32(data, 20, 0xFFFFFFFF)
    elif damage == 'element_reserved':
        data = _u32(data, 28, 1)
    elif damage == 'element_zero':
        data = data[:32] + bytes(2) + data[34:]
    elif damage == 'input_chain':
        data = _mpet([_matrix(3, 5), _matrix(4, 1)])
    elif damage == 'output_chain':
        data = data[:10] + pack('>H', 1) + data[12:]
    elif damage == 'matrix_count':
        data = _mpet([_matrix()[:-4]])
    elif damage == 'matrix_extra':
        data = _mpet([_matrix() + bytes(4)])
    elif damage == 'expansion_count':
        data = _mpet([_element(b'bACS', 3, 3)])
    else:
        data = _mpet([_element(b'eACS', 3, 1, b'abcd')])
    with pytest.raises(PngValidationError, match='ICC'):
        validate_mpet(data)


@pytest.mark.parametrize('damage', ['header', 'dimensions', 'grid', 'unused', 'short_data', 'extra_data', 'huge_grid'])
def test_mpet_clut_dimensions_and_sizes(damage: str) -> None:
    element = _clut()
    if damage == 'header':
        element = element[:24]
    elif damage == 'dimensions':
        element = _element(b'clut', 17, 3, bytes(16))
    elif damage == 'grid':
        element = element[:12] + b'\x01' + element[13:]
    elif damage == 'unused':
        element = element[:15] + b'\x01' + element[16:]
    elif damage == 'short_data':
        element = element[:-4]
    elif damage == 'extra_data':
        element += bytes(4)
    else:
        element = element[:12] + bytes((255,)) * 3 + element[15:]
    with pytest.raises(PngValidationError, match='CLUT'):
        validate_mpet(_mpet([element]))


@pytest.mark.parametrize('function', [0, 1, 2])
@pytest.mark.parametrize('middle', [False, True])
def test_mpet_formula_and_sampled_segment_layouts(function: int, middle: bool) -> None:
    curve = (
        _curve([_formula(function), _sample((0.5,)), _formula(function)], (0, 1))
        if middle
        else _curve([_formula(function)])
    )
    validate_mpet(_mpet([_curves([curve] * 3)]))
    if middle:
        validate_mpet(_mpet([_curves([_curve([_formula(), _sample(), _formula()], (0, 0))])]))


@pytest.mark.parametrize(
    'damage',
    [
        'set_channels',
        'curve_table',
        'curve_offset',
        'curve_size',
        'curve_signature',
        'curve_reserved',
        'zero_segments',
        'segment_reserved',
        'breakpoint_count',
        'breakpoint_order',
        'first_sampled',
        'last_sampled',
        'formula_function',
        'formula_reserved',
        'formula_size',
        'zero_samples',
        'sample_count',
        'extra_curve',
    ],
)
def test_mpet_curve_positions_and_segment_bounds(damage: str) -> None:
    curve = _curve([_formula(), _sample(), _formula()], (0, 1))
    if damage == 'curve_signature':
        curve = b'curv' + curve[4:]
    elif damage == 'curve_reserved':
        curve = _u32(curve, 4, 1)
    elif damage == 'zero_segments':
        curve = curve[:8] + bytes(2) + curve[10:]
    elif damage == 'segment_reserved':
        curve = curve[:10] + b'\0\x01' + curve[12:]
    elif damage == 'breakpoint_count':
        curve = curve[:8] + b'\xff\xff' + curve[10:]
    elif damage == 'breakpoint_order':
        curve = _curve([_formula(), _sample(), _formula()], (1, 0))
    elif damage == 'first_sampled':
        curve = _curve([_sample(), _formula()], (0,))
    elif damage == 'last_sampled':
        curve = _curve([_formula(), _sample()], (0,))
    elif damage == 'formula_function':
        curve = _curve([b'parf' + bytes(4) + pack('>HH', 3, 0)])
    elif damage == 'formula_reserved':
        curve = _curve([b'parf' + bytes(4) + pack('>HH', 0, 1) + bytes(16)])
    elif damage == 'formula_size':
        curve = _curve([_formula()[:-4]])
    elif damage == 'zero_samples':
        curve = _curve([_formula(), _sample(()), _formula()], (0, 1))
    elif damage == 'sample_count':
        curve = _curve([_formula(), b'samf' + bytes(4) + pack('>I', 0xFFFFFFFF), _formula()], (0, 1))
    elif damage == 'extra_curve':
        curve += bytes(4)
    element = _curves([curve] * 3)
    if damage == 'set_channels':
        element = element[:10] + pack('>H', 1) + element[12:]
    elif damage == 'curve_table':
        element = element[:20]
    elif damage == 'curve_offset':
        element = _u32(element, 12, 12)
    elif damage == 'curve_size':
        element = _u32(element, 16, 8)
    with pytest.raises(PngValidationError, match='ICC'):
        validate_mpet(_mpet([element]))


@pytest.mark.parametrize('bits', [0, 0x80000000, 0x00800000, 0x7F7FFFFF, 0xBF800000])
def test_mpet_signed_zero_and_normal_floats(bits: int) -> None:
    matrix = _matrix()
    validate_mpet(_mpet([_u32(matrix, 12, bits)]))


@pytest.mark.parametrize('bits', [1, 0x80000001, 0x7F800000, 0xFF800000, 0x7FC00000])
@pytest.mark.parametrize('location', ['matrix', 'clut', 'formula', 'sample', 'breakpoint'])
def test_mpet_rejects_subnormal_and_nonfinite_floats(bits: int, location: str) -> None:
    if location == 'matrix':
        element = _u32(_matrix(), 12, bits)
    elif location == 'clut':
        element = _u32(_clut(), 28, bits)
    else:
        formula = _formula()
        sample = _sample()
        if location == 'formula':
            formula = _u32(formula, 12, bits)
        elif location == 'sample':
            sample = _u32(sample, 12, bits)
        curve = _curve([formula, sample, _formula()], (0, 1))
        if location == 'breakpoint':
            curve = _u32(curve, 12, bits)
        element = _curves([curve] * 3)
    with pytest.raises(PngValidationError, match='float32'):
        validate_mpet(_mpet([element]))


def _with_mpet(profile: bytes, tag: bytes, payload: bytes) -> bytes:
    (count,) = unpack_from('>I', profile, 128)
    entries = [unpack_from('>4sII', profile, 132 + 12 * index) for index in range(count)]
    tags = [(kind, profile[offset : offset + size]) for kind, offset, size in entries] + [(tag, payload)]
    table = bytearray()
    body = bytearray()
    for kind, value in tags:
        table.extend(pack('>4sII', kind, 132 + 12 * len(tags) + len(body), len(value)))
        body.extend(value)
        body.extend(bytes(-len(body) % 4))
    header = bytearray(profile[:128])
    header[84:100] = bytes(16)
    result = bytes(header) + pack('>I', len(tags)) + bytes(table) + bytes(body)
    return _u32(result, 0, len(result))


@pytest.mark.parametrize('tag', [b'D2B0', b'D2B1', b'D2B2', b'D2B3', b'B2D0', b'B2D1', b'B2D2', b'B2D3'])
def test_mpet_transform_tag_types_and_channel_context(assets_dir: Path, tag: bytes) -> None:
    profile = assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()
    PngIccProfile('Optional mpet', _with_mpet(profile, tag, _mpet([_matrix()]))).validate_profile_tags()
    with pytest.raises(PngValidationError, match='channel counts disagree'):
        PngIccProfile('Wrong channels', _with_mpet(profile, tag, _mpet([_matrix(1, 1)]))).validate_profile_tags()
    with pytest.raises(PngValidationError, match='invalid tag type'):
        PngIccProfile('Wrong type', _with_mpet(profile, tag, b'XYZ ' + bytes(16))).validate_profile_tags()


@pytest.mark.parametrize('tag', [b'D2B0', b'D2B3', b'B2D0', b'B2D3'])
def test_mpet_gray_channel_direction(tag: bytes) -> None:
    profile = bytes(12) + b'mntrGRAYLab '
    inputs, outputs = (1, 3) if tag.startswith(b'D2B') else (3, 1)
    data = _mpet([_matrix(inputs, outputs)])
    validate_mpet(data)
    validate_mpet_context(profile, tag, memoryview(data))
    reversed_data = _mpet([_matrix(outputs, inputs)])
    with pytest.raises(PngValidationError, match='channel counts disagree'):
        validate_mpet_context(profile, tag, memoryview(reversed_data))


@pytest.mark.parametrize('representation', ['image', 'document'])
@pytest.mark.parametrize('mode', ['known', 'unknown', 'damaged'])
def test_mpet_png_roundtrip_and_write_protection(
    assets_dir: Path,
    png_suite_dir: Path,
    tmp_path: Path,
    representation: str,
    mode: str,
) -> None:
    profile = assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()
    element = _element(b'zzzz', 3, 3, b'opaque future data\xff') if mode == 'unknown' else _matrix()
    if mode == 'damaged':
        element = element[:-4]
    profile = _with_mpet(profile, b'D2B0', _mpet([element]))
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(PngIccProfile('Multi-process', profile))
    document = image.to_document()
    raw = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    restored = PngImage.parse(raw)
    assert restored.find_metadata(b'iCCP')[0].profile == profile
    result = restored if representation == 'image' else PngDocument.parse(raw)
    if mode != 'damaged':
        written = PngImage.parse(result.dump_to_bytes())
        assert written.find_metadata(b'iCCP')[0].profile == profile
        assert written.bitmap == image.bitmap
        return
    stream = BytesIO(b'unchanged')
    with pytest.raises(PngValidationError, match='matrix coefficient count'):
        result.dump(stream)
    assert stream.getvalue() == b'unchanged'
    target = tmp_path.joinpath('existing.png')
    target.write_bytes(b'unchanged')
    with pytest.raises(PngValidationError, match='matrix coefficient count'):
        result.save(target)
    assert target.read_bytes() == b'unchanged'


def test_unknown_inner_curve_segment_is_reported_as_unsupported() -> None:
    curve = _curve([_formula(), b'????' + bytes(8), _formula()], (0, 1))
    with pytest.raises(PngUnsupportedError, match='segment encoding'):
        validate_mpet(_mpet([_curves([curve])]))
