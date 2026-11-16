from struct import pack

import pytest

from png import PngIccProfile, PngValidationError
from png._icc_misc import validate_misc, validate_misc_context
from tests.test_icc_tags import _lut16, _rebuild, _tags


def _payload(kind, body):
    return kind + bytes(4) + body


@pytest.mark.parametrize(('kind', 'body'), [
    (b'ui08', b'abc'), (b'ui16', bytes(6)), (b'ui32', bytes(8)), (b'ui64', bytes(16)),
    (b'uf32', bytes(12)), (b'data', bytes(4) + b'ASCII\0'), (b'data', pack('>I', 1) + b'\xff\0'),
    (b'dtim', pack('>6H', 65535, 12, 31, 23, 59, 59)), (b'sig ', b'CRT '),
    (b'meas', bytes(28)), (b'view', bytes(28)), (b'clro', pack('>I', 3) + bytes((2, 0, 1))),
    (b'cicp', bytes((9, 16, 0, 1))), (b'chrm', pack('>HH', 1, 0) + bytes(8)),
])
def test_optional_icc_encodings_accept_valid_storage(kind, body):
    validate_misc(_payload(kind, body))


@pytest.mark.parametrize(('kind', 'body'), [
    (b'ui16', bytes(3)), (b'ui32', bytes(7)), (b'ui64', bytes(15)), (b'uf32', bytes(2)),
    (b'data', pack('>I', 2)), (b'data', bytes(4) + b'no terminator'),
    (b'data', bytes(4) + b'\x80\0'), (b'sig ', bytes(3)), (b'view', bytes(27)),
    (b'view', bytes(24) + pack('>I', 9)), (b'meas', pack('>I', 3) + bytes(24)),
    (b'meas', bytes(16) + pack('>I', 3) + bytes(8)), (b'meas', bytes(24) + pack('>I', 9)),
    (b'dtim', pack('>6H', 2025, 0, 1, 0, 0, 0)),
    (b'dtim', pack('>6H', 2025, 1, 1, 0, 0, 60)),
    (b'clro', pack('>I', 3) + bytes((0, 0, 2))),
    (b'clro', pack('>I', 0xFFFFFFFF)), (b'cicp', bytes((9, 16, 0, 2))),
    (b'chrm', pack('>HH', 3, 0) + bytes(8)),
])
def test_optional_icc_encodings_reject_malformed_storage(kind, body):
    with pytest.raises(PngValidationError):
        validate_misc(_payload(kind, body))


@pytest.mark.parametrize('encoding', [1, 2, 3, 4])
def test_standard_phosphor_coordinates_match_the_declared_encoding(encoding):
    values = {1: (640, 330, 300, 600, 150, 60), 2: (630, 340, 310, 595, 155, 70),
              3: (640, 330, 290, 600, 150, 60), 4: (625, 340, 280, 605, 155, 70)}[encoding]
    coordinates = [(v * 65536 + 500) // 1000 for v in values]
    data = _payload(b'chrm', pack('>HH6I', 3, encoding, *coordinates))
    validate_misc(data)
    with pytest.raises(PngValidationError, match='phosphor'):
        validate_misc(data[:-4] + bytes(4))


@pytest.mark.parametrize(('device', 'category', 'matrix', 'valid'), [
    (b'RGB ', b'mntr', 0, True), (b'XYZ ', b'scnr', 0, True), (b'YCbr', b'mntr', 9, True),
    (b'RGB ', b'mntr', 1, False), (b'YCbr', b'scnr', 0, False),
    (b'GRAY', b'mntr', 0, False), (b'RGB ', b'prtr', 0, False),
])
def test_icc_cicp_context(device, category, matrix, valid):
    header = bytes(12) + category + device
    data = memoryview(_payload(b'cicp', bytes((9, 16, matrix, 1))))
    if valid:
        validate_misc_context(header, b'cicp', data)
    else:
        with pytest.raises(PngValidationError):
            validate_misc_context(header, b'cicp', data)


def test_icc_optional_tag_type_and_private_type_dispatch(assets_dir):
    profile = assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()
    tags = _tags(profile)
    tags[b'meas'] = _payload(b'sig ', b'TEST')
    with pytest.raises(PngValidationError, match='invalid tag type'):
        PngIccProfile('Optional type', _rebuild(profile, tags)).validate_profile_tags()
    del tags[b'meas']
    tags[b'priv'] = _payload(b'ui64', bytes(7))
    with pytest.raises(PngValidationError, match='numeric array'):
        PngIccProfile('Private array', _rebuild(profile, tags)).validate_profile_tags()


@pytest.mark.parametrize(('category', 'missing'), [(b'prtr', b'clrt'), (b'link', b'clrt'), (b'link', b'clot')])
def test_nclr_conditional_colorant_tables(assets_dir, category, missing):
    profile = assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()
    tags = _tags(profile)
    tags.update({name: _lut16() for name in (b'A2B0', b'A2B1', b'A2B2', b'B2A0', b'B2A1', b'B2A2')})
    tags[b'gamt'] = _lut16(3, 1)
    tags[b'pseq'] = b'pseq' + bytes(8)
    table = _payload(b'clrt', pack('>I', 3) + b''.join(bytes((65 + i,)) + bytes(31) + bytes(6) for i in range(3)))
    tags.update({b'clrt': table, b'clot': table})
    if category == b'prtr':
        del tags[b'clot']
    rebuilt = _rebuild(profile, tags, color_space=b'3CLR', profile_class=category)
    if category == b'link':
        rebuilt = rebuilt[:20] + b'3CLR' + rebuilt[24:]
    PngIccProfile('NCLR', rebuilt).validate_profile_tags()
    del tags[missing]
    rebuilt = _rebuild(rebuilt, tags)
    with pytest.raises(PngValidationError, match=missing.decode()):
        PngIccProfile('Missing colorants', rebuilt).validate_profile_tags()
