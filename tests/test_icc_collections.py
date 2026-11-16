from io import BytesIO
from struct import pack

import pytest

from png import PngIccProfile, PngImage, PngValidationError
from png._icc_collections import validate_dictionary, validate_response_curves
from tests.test_icc_records import _localized, _u32, _with_record


def _dictionary(records, stride=16):
    body, table, offsets = bytearray(), bytearray(), {}
    start = 16 + stride * len(records)
    for record in records:
        for index, item in enumerate(record[: stride // 8]):
            if item is None:
                table.extend(bytes(8))
                continue
            value = item.encode('utf-16-be') if index < 2 else item
            if value not in offsets:
                offsets[value] = start + len(body)
                body.extend(value)
                body.extend(bytes(-len(body) % 4))
            table.extend(pack('>II', offsets[value], len(value)))
    return b'dict' + bytes(4) + pack('>II', len(records), stride) + table + body


def _response(codes=((0, 32768, 65535),), unit=b'StaT'):
    channels = len(codes)
    curve = unit + b''.join(pack('>I', len(channel)) for channel in codes) + bytes(12 * channels)
    curve += b''.join(pack('>HHi', code, 0, -65536) for channel in codes for code in channel)
    return b'rcs2' + bytes(4) + pack('>HHI', channels, 1, 16) + curve


@pytest.mark.parametrize('stride', [16, 24, 32])
@pytest.mark.parametrize('value', [None, '', 'Value', 'PNG\U0001f600'])
def test_dictionary_optional_values_localization_and_shared_items(stride, value):
    records = [('One', value, _localized('Label'), _localized('Value')), ('Two', value, _localized('Label'), None)]
    validate_dictionary(_dictionary(records, stride))
    validate_dictionary(_dictionary([], stride))


@pytest.mark.parametrize(
    'damage',
    [
        'header',
        'stride',
        'count',
        'name_missing',
        'name_empty',
        'duplicate',
        'offset',
        'unaligned',
        'short',
        'odd',
        'utf16',
        'null',
        'padding',
        'display_type',
    ],
)
def test_dictionary_bounds_and_unicode_errors(damage):
    data = _dictionary([('Name', 'Value', _localized('Label'), None)], 32)
    if damage == 'header':
        data = data[:15]
    elif damage == 'stride':
        data = _u32(data, 12, 20)
    elif damage == 'count':
        data = _u32(data, 8, 0xFFFFFFFF)
    elif damage == 'name_missing':
        data = _u32(data, 16, 0)
    elif damage == 'name_empty':
        data = _u32(data, 20, 0)
    elif damage == 'duplicate':
        data = _dictionary([('Same', None, None, None)] * 2)
    elif damage == 'offset':
        data = _u32(data, 16, 16)
    elif damage == 'unaligned':
        data = _u32(data, 16, 49)
    elif damage == 'short':
        data = _u32(data, 20, 0xFFFFFFFE)
    elif damage == 'odd':
        data = _u32(data, 20, 3)
    elif damage == 'utf16':
        data = data[:48] + b'\xd8\0' + data[50:]
    elif damage == 'null':
        data = data[:54] + bytes(2) + data[56:]
    elif damage == 'padding':
        data = _dictionary([('A', None, None, None)])[:-1] + b'\1'
    else:
        data = _dictionary([('A', None, b'zzzz' + bytes(12), None)], 32)
    with pytest.raises(PngValidationError, match='ICC'):
        validate_dictionary(data)


def test_dictionary_absent_optional_size_is_undefined_and_zero_size_display_is_valid():
    data = _dictionary([('Name', None, None, None)], 32)
    validate_dictionary(_u32(data, 28, 0xFFFFFFFF))
    # A nonzero display offset and zero size means do not display the name.
    data = _u32(data, 32, len(data))
    validate_dictionary(data)


@pytest.mark.parametrize('codes', [(), ((),), ((0,),), ((0, 65535),), ((0, 10), (0, 10, 65535), ())])
def test_response_curve_counts_and_channel_arrays(codes):
    validate_response_curves(_response(codes))


@pytest.mark.parametrize(
    'damage', ['header', 'table', 'offset', 'count', 'short', 'reserved', 'descending', 'repeated']
)
def test_response_curve_truncation_and_code_order(damage):
    data = _response()
    if damage == 'header':
        data = data[:11]
    elif damage == 'table':
        data = data[:15]
    elif damage == 'offset':
        data = _u32(data, 12, 0xFFFFFFFF)
    elif damage == 'count':
        data = _u32(data, 20, 0xFFFFFFFF)
    elif damage == 'short':
        data = data[:-1]
    elif damage == 'reserved':
        data = data[:38] + b'\0\1' + data[40:]
    elif damage == 'descending':
        data = _response(((20, 10),))
    else:
        data = _response(((10, 10),))
    with pytest.raises(PngValidationError, match='ICC'):
        validate_response_curves(data)


@pytest.mark.parametrize('kind', [b'meta', b'resp'])
@pytest.mark.parametrize('damaged', [False, True])
def test_collections_are_preserved_and_checked_before_png_writes(assets_dir, png_suite_dir, kind, damaged):
    source = assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()
    payload = _dictionary([('Name', 'Value', None, None)]) if kind == b'meta' else _response(((0, 65535),) * 3)
    if damaged:
        payload = _u32(payload, 16 if kind == b'meta' else 12, 0xFFFFFFFF)
    profile = _with_record(source, kind, payload)
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(PngIccProfile('Collection', profile))
    document = image.to_document()
    if damaged:
        for model in (image, document):
            stream = BytesIO(b'unchanged')
            with pytest.raises(PngValidationError):
                model.dump(stream)
            assert stream.getvalue() == b'unchanged'
    else:
        for model in (image, document):
            restored = PngImage.parse(model.dump_to_bytes())
            assert restored.find_metadata(b'iCCP')[0].profile == profile
