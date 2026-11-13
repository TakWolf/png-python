"""ICC LUT layout vectors, plus mutations of the official ICC v4 sample."""

from io import BytesIO
from pathlib import Path
from struct import pack, unpack_from

import pytest

from png import PngDocument, PngIccProfile, PngImage, PngValidationError
from png._icc_lut import validate_lut, validate_lut_context


_IDENTITY = pack('>9i', 65536, 0, 0, 0, 65536, 0, 0, 0, 65536)


def _legacy(kind: bytes, inputs: int = 3, outputs: int = 3, *, grid: int = 2,
            in_entries: int = 2, out_entries: int = 2) -> bytes:
    header = kind + bytes(4) + bytes((inputs, outputs, grid, 0)) + _IDENTITY
    if kind == b'mft1':
        return header + bytes(256 * inputs + grid ** inputs * outputs + 256 * outputs)
    return (header + pack('>HH', in_entries, out_entries)
            + bytes(2 * (in_entries * inputs + grid ** inputs * outputs + out_entries * outputs)))


def _curve(*, gamma: bool = False, parametric: bool = False) -> bytes:
    if parametric:
        return b'para' + bytes(4) + pack('>HHI', 0, 0, 65536)
    return b'curv' + bytes(4) + pack('>I', int(gamma)) + (pack('>H', 256) if gamma else b'')


def _multi(kind: bytes, combination: str, *, inputs: int = 3, outputs: int = 3,
           precision: int = 2, gamma: bool = False, parametric: bool = False) -> bytes:
    # Store elements in processing order, unlike the official profile's order.
    middle = inputs if kind == b'mBA ' else outputs
    curve = _curve(gamma=gamma, parametric=parametric)
    padded_curve = curve + bytes(-len(curve) % 4)
    elements = {
        'B': padded_curve * middle,
        'X': _IDENTITY + bytes(12),
        'M': padded_curve * middle,
        'C': bytes((2,)) * inputs + bytes(16 - inputs) + bytes((precision,)) + bytes(3)
             + bytes(2 ** inputs * outputs * precision),
        'A': padded_curve * (outputs if kind == b'mBA ' else inputs),
    }
    offsets = {}
    body = bytearray()
    for name in combination:
        offsets[name] = 32 + len(body)
        body.extend(elements[name])
        body.extend(bytes(-len(body) % 4))
    return (kind + bytes(4) + bytes((inputs, outputs, 0, 0))
            + b''.join(pack('>I', offsets.get(name, 0)) for name in 'BXMCA') + bytes(body))


def _u32(data: bytes, offset: int, value: int) -> bytes:
    return data[:offset] + pack('>I', value) + data[offset + 4:]


@pytest.mark.parametrize('kind', [b'mft1', b'mft2'])
@pytest.mark.parametrize(('inputs', 'outputs'), [(1, 1), (1, 3), (3, 1), (3, 3), (15, 1)])
def test_legacy_lut_sizes_and_channel_dimensions(kind: bytes, inputs: int, outputs: int) -> None:
    validate_lut(_legacy(kind, inputs, outputs))


@pytest.mark.parametrize(('entries', 'grid'), [(2, 2), (4096, 255)])
def test_lut16_table_count_boundaries(entries: int, grid: int) -> None:
    validate_lut(_legacy(b'mft2', 1, 1, grid=grid, in_entries=entries, out_entries=entries))


@pytest.mark.parametrize('kind', [b'mft1', b'mft2'])
@pytest.mark.parametrize('damage', ['header', 'zero_inputs', 'too_many_inputs', 'zero_outputs',
                                    'too_many_outputs', 'zero_grid', 'one_grid', 'reserved',
                                    'short_table', 'extra_table', 'huge_grid'])
def test_legacy_lut_malformed_headers_and_tables(kind: bytes, damage: str) -> None:
    data = bytearray(_legacy(kind))
    if damage == 'header':
        data = data[:47]
    elif damage == 'zero_inputs':
        data[8] = 0
    elif damage == 'too_many_inputs':
        data[8] = 255
    elif damage == 'zero_outputs':
        data[9] = 0
    elif damage == 'too_many_outputs':
        data[9] = 255
    elif damage == 'zero_grid':
        data[10] = 0
    elif damage == 'one_grid':
        data[10] = 1
    elif damage == 'reserved':
        data[11] = 1
    elif damage == 'short_table':
        data = data[:-1]
    elif damage == 'extra_table':
        data.extend(bytes(1))
    else:
        data[8], data[10] = 15, 255  # Size arithmetic must not allocate this CLUT.
    with pytest.raises(PngValidationError, match='ICC LUT'):
        validate_lut(bytes(data))


@pytest.mark.parametrize('offset', [48, 50])
@pytest.mark.parametrize('count', [0, 1, 4097, 65535])
def test_lut16_invalid_table_counts(offset: int, count: int) -> None:
    data = _legacy(b'mft2')
    data = data[:offset] + pack('>H', count) + data[offset + 2:]
    with pytest.raises(PngValidationError, match='ICC LUT16 table counts'):
        validate_lut(data)


@pytest.mark.parametrize('kind', [b'mAB ', b'mBA '])
@pytest.mark.parametrize('combination', ['B', 'MXB', 'ACB', 'ACMXB'])
@pytest.mark.parametrize('encoding', ['identity', 'gamma', 'parametric'])
def test_multifunction_lut_allowed_combinations_and_curve_encodings(
        kind: bytes, combination: str, encoding: str,
) -> None:
    validate_lut(_multi(kind, combination, gamma=encoding == 'gamma', parametric=encoding == 'parametric'))


@pytest.mark.parametrize('kind', [b'mAB ', b'mBA '])
@pytest.mark.parametrize('precision', [1, 2])
@pytest.mark.parametrize(('inputs', 'outputs'), [(1, 3), (3, 1)])
def test_multifunction_lut_asymmetric_channels_and_clut_precision(
        kind: bytes, precision: int, inputs: int, outputs: int,
) -> None:
    validate_lut(_multi(kind, 'ACB', inputs=inputs, outputs=outputs, precision=precision))


@pytest.mark.parametrize('kind', [b'mAB ', b'mBA '])
@pytest.mark.parametrize('combination', ['', 'A', 'C', 'XB', 'MB', 'AB', 'CB', 'ACMB'])
def test_multifunction_lut_disallowed_combinations(kind: bytes, combination: str) -> None:
    with pytest.raises(PngValidationError, match='combination'):
        validate_lut(_multi(kind, combination))


@pytest.mark.parametrize('kind', [b'mAB ', b'mBA '])
@pytest.mark.parametrize('damage', ['header', 'reserved', 'zero_channels', 'too_many_channels',
                                    'no_clut', 'matrix_channels', 'matrix_extent', 'offset_header',
                                    'offset_odd', 'offset_outside', 'curve_count', 'curve_type',
                                    'curve_reserved', 'curve_padding', 'para_function', 'para_reserved',
                                    'clut_header', 'clut_grid', 'clut_unused', 'clut_precision',
                                    'clut_reserved', 'clut_data', 'clut_huge'])
def test_multifunction_lut_internal_bounds(kind: bytes, damage: str) -> None:
    data = bytearray(_multi(kind, 'BMXAC', gamma=True))
    b_curves, matrix, _, clut, _ = unpack_from('>5I', data, 12)
    if damage == 'header':
        data = data[:31]
    elif damage == 'reserved':
        data[10] = 1
    elif damage == 'zero_channels':
        data[8] = 0
    elif damage == 'too_many_channels':
        data[9] = 16
    elif damage == 'no_clut':
        data = bytearray(_multi(kind, 'B', inputs=1, outputs=3))
    elif damage == 'matrix_channels':
        data = bytearray(_multi(kind, 'MXB', inputs=1, outputs=1))
    elif damage == 'matrix_extent':
        data[16:20] = pack('>I', len(data) - 4)
    elif damage == 'offset_header':
        data[12:16] = pack('>I', 16)
    elif damage == 'offset_odd':
        data[12:16] = pack('>I', 33)
    elif damage == 'offset_outside':
        data[12:16] = pack('>I', 0xFFFFFFFC)
    elif damage == 'curve_count':
        data[b_curves + 8:b_curves + 12] = pack('>I', 0xFFFFFFFF)
    elif damage == 'curve_type':
        data[b_curves:b_curves + 4] = b'XYZ '
    elif damage == 'curve_reserved':
        data[b_curves + 4] = 1
    elif damage == 'curve_padding':
        data[b_curves + 14] = 1
    elif damage in ('para_function', 'para_reserved'):
        data = bytearray(_multi(kind, 'B', parametric=True))
        data[40 if damage == 'para_function' else 42] = 1
    elif damage == 'clut_header':
        data = data[:clut + 19]
    elif damage == 'clut_grid':
        data[clut] = 1
    elif damage == 'clut_unused':
        data[clut + 3] = 2
    elif damage == 'clut_precision':
        data[clut + 16] = 3
    elif damage == 'clut_reserved':
        data[clut + 17] = 1
    elif damage == 'clut_data':
        data = data[:-1]
    else:
        data[clut:clut + 3] = bytes((255,)) * 3
    with pytest.raises(PngValidationError, match='ICC'):
        validate_lut(bytes(data))


@pytest.mark.parametrize('kind', [b'mAB ', b'mBA '])
def test_multifunction_lut_shared_curve_groups_and_suffixes(kind: bytes) -> None:
    data = _multi(kind, 'BMXAC', inputs=1 if kind == b'mAB ' else 3,
                  outputs=3 if kind == b'mAB ' else 1)
    first, = unpack_from('>I', data, 12)
    # A's single curve aliases the second of the three B/M curves.
    data = _u32(_u32(data, 20, first), 28, first + 12)
    validate_lut(data)


@pytest.mark.parametrize('kind', [b'mAB ', b'mBA '])
def test_final_embedded_curve_can_leave_padding_outside_the_tag(kind: bytes) -> None:
    data = _multi(kind, 'B', gamma=True)
    validate_lut(data[:-2])  # The containing ICC directory owns the final tag padding.
    with pytest.raises(PngValidationError, match='curve count exceeds'):
        validate_lut(data[:-3])


def test_reverse_lut_requires_an_xyz_or_lab_pcs() -> None:
    data = _multi(b'mBA ', 'B')
    validate_lut(data)
    with pytest.raises(PngValidationError, match='requires XYZ or Lab PCS'):
        validate_lut_context(bytes(12) + b'linkRGB RGB ', b'B2A0', data)


@pytest.mark.parametrize(('signature', 'device', 'pcs', 'inputs', 'outputs'), [
    (b'A2B0', b'RGB ', b'Lab ', 3, 3), (b'A2B1', b'GRAY', b'XYZ ', 1, 3),
    (b'B2A0', b'GRAY', b'XYZ ', 3, 1), (b'gamt', b'RGB ', b'Lab ', 3, 1),
    (b'pre0', b'RGB ', b'XYZ ', 3, 3),
])
def test_lut_channels_match_transform_direction(
        signature: bytes, device: bytes, pcs: bytes, inputs: int, outputs: int,
) -> None:
    profile = bytes(12) + b'mntr' + device + pcs
    data = _legacy(b'mft2', inputs, outputs)
    validate_lut(data)
    validate_lut_context(profile, signature, data)
    data = _legacy(b'mft2', 2, 2)
    validate_lut(data)
    with pytest.raises(PngValidationError, match='channel counts disagree'):
        validate_lut_context(profile, signature, data)


def test_legacy_lut_matrix_identity_depends_on_pcs_input() -> None:
    data = _legacy(b'mft2')
    nonidentity = _u32(data, 12, 32768)
    for signature, pcs in ((b'A2B0', b'XYZ '), (b'B2A0', b'Lab ')):
        with pytest.raises(PngValidationError, match='matrix must be identity'):
            validate_lut_context(bytes(12) + b'mntrRGB ' + pcs, signature, nonidentity)
    validate_lut_context(bytes(12) + b'mntrRGB XYZ ', b'B2A0', nonidentity)


@pytest.mark.parametrize('representation', ['image', 'document'])
def test_official_lut_corruption_is_preserved_but_not_written(
        assets_dir: Path, png_suite_dir: Path, tmp_path: Path, representation: str,
) -> None:
    profile = assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()
    count, = unpack_from('>I', profile, 128)
    for index in range(count):
        signature, offset, _ = unpack_from('>4sII', profile, 132 + 12 * index)
        if signature == b'A2B0':
            # The containing ICC directory and LUT header remain legal.
            profile = _u32(profile, offset + 12, 0xFFFFFFFC)
            break
    else:
        pytest.fail('Official profile has no A2B0 tag')
    metadata = PngIccProfile('Bad LUT offset', profile)
    metadata.validate_profile_structure()
    with pytest.raises(PngValidationError, match='LUT element offset'):
        metadata.validate_profile_tags()
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(metadata)
    document = image.to_document()
    raw = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    restored = PngImage.parse(raw)
    assert restored.find_metadata(b'iCCP')[0].profile == profile
    result = restored if representation == 'image' else PngDocument.parse(raw)
    stream = BytesIO(b'unchanged')
    with pytest.raises(PngValidationError, match='LUT element offset'):
        result.dump(stream)
    assert stream.getvalue() == b'unchanged'
    target = tmp_path.joinpath('existing.png')
    target.write_bytes(b'unchanged')
    with pytest.raises(PngValidationError, match='LUT element offset'):
        result.save(target)
    assert target.read_bytes() == b'unchanged'
