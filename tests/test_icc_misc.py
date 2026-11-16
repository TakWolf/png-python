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


@pytest.mark.parametrize('state', [b'scoe', b'sape', b'fpce', b'rhoc', b'rpoc'])
def test_colorimetric_image_state_requires_viewing_conditions(assets_dir, state):
    profile = assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()
    tags = _tags(profile)
    tags.pop(b'chad', None)
    tags[b'ciis'] = _payload(b'sig ', state)
    with pytest.raises(PngValidationError, match='view'):
        PngIccProfile('Image state', _rebuild(profile, tags)).validate_profile_tags()
    tags[b'view'] = _payload(b'view', bytes(28))
    if state in (b'rhoc', b'rpoc'):
        with pytest.raises(PngValidationError, match='chad'):
            PngIccProfile('Missing adaptation', _rebuild(profile, tags)).validate_profile_tags()
        tags[b'chad'] = _payload(b'sf32', pack('>9i', 65536, 0, 0, 0, 65536, 0, 0, 0, 65536))
    PngIccProfile('Image state', _rebuild(profile, tags)).validate_profile_tags()


def test_reserved_colorimetric_image_state_is_rejected(assets_dir):
    profile = assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()
    tags = _tags(profile)
    tags[b'ciis'] = _payload(b'sig ', b'none')
    with pytest.raises(PngValidationError, match='reserved'):
        PngIccProfile('Reserved state', _rebuild(profile, tags)).validate_profile_tags()


def test_display_white_and_abstract_space_requirements(icc_profile_bytes):
    from png._icc_header import validate_header_fields
    header = bytearray(icc_profile_bytes)
    header[84:100] = bytes(16)
    header[12:20] = b'abstRGB '
    with pytest.raises(PngValidationError, match='PCS to PCS'):
        validate_header_fields(bytes(header))

    header[12:20] = b'mntrBAD!'
    with pytest.raises(PngValidationError, match='colour space'):
        validate_header_fields(bytes(header))


def test_v4_display_media_white_is_the_pcs_illuminant(assets_dir):
    profile = assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()
    tags = _tags(profile)
    tags[b'wtpt'] = _payload(b'XYZ ', pack('>3i', 60000, 65536, 70000))
    with pytest.raises(PngValidationError, match='media white'):
        PngIccProfile('Display white', _rebuild(profile, tags, profile_class=b'mntr')).validate_profile_tags()


@pytest.mark.parametrize('state', [b'scoe', b'sape', b'fpce'])
def test_declared_non_d50_adopted_white_requires_chromatic_adaptation(assets_dir, state):
    profile = assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()
    tags = _tags(profile)
    tags.pop(b'chad', None)
    tags[b'ciis'] = _payload(b'sig ', state)
    tags[b'view'] = _payload(b'view', pack('>6iI', 62290, 65536, 71372, 0, 0, 0, 2))
    with pytest.raises(PngValidationError, match='chad'):
        PngIccProfile('Declared source white', _rebuild(profile, tags)).validate_profile_tags()
    tags[b'view'] = _payload(b'view', pack('>6iI', 63190, 65536, 54061, 0, 0, 0, 1))
    PngIccProfile('D50 source white', _rebuild(profile, tags)).validate_profile_tags()


@pytest.mark.parametrize('text,valid', [(b'ICCHDAT Example\0', True), (b'CGATS.5\nopaque measurement data\0', True),
                                       (b'ICCHDAT\0', False), (b'ICCHDAT \0', False),
                                       (b'ICCHDATXExample\0', False), (b'short\0', False)])
def test_characterization_target_identifier_format(assets_dir, text, valid):
    profile = assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()
    tags = _tags(profile)
    tags[b'targ'] = _payload(b'text', text)
    metadata = PngIccProfile('Characterization', _rebuild(profile, tags))
    if valid:
        metadata.validate_profile_tags()
    else:
        with pytest.raises(PngValidationError, match='target'):
            metadata.validate_profile_tags()
