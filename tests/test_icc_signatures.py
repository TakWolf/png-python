"""ICC.1:2022 Tables 27--29 values, with PNG preservation/write checks."""

from io import BytesIO
from struct import pack

import pytest

from png import PngDocument, PngIccProfile, PngImage, PngValidationError
from tests.test_icc_tags import _rebuild, _tags

_TECHNOLOGIES = (
    b'fscn',
    b'dcam',
    b'rscn',
    b'ijet',
    b'twax',
    b'epho',
    b'esta',
    b'dsub',
    b'rpho',
    b'fprn',
    b'vidm',
    b'vidc',
    b'pjtv',
    b'CRT ',
    b'PMD ',
    b'AMD ',
    b'LCD ',
    b'OLED',
    b'KPCD',
    b'imgs',
    b'grav',
    b'offs',
    b'silk',
    b'flex',
    b'mpfs',
    b'mpfr',
    b'dmpc',
    b'dcpj',
)


def _signature(value):
    return b'sig ' + bytes(4) + value


@pytest.fixture
def profile(assets_dir):
    return assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()


@pytest.mark.parametrize('technology', _TECHNOLOGIES)
def test_defined_icc_technology_signatures(profile, technology):
    tags = _tags(profile)
    tags[b'tech'] = _signature(technology)
    PngIccProfile('Technology vector', _rebuild(profile, tags)).validate_profile_tags()


@pytest.mark.parametrize('tag', [b'rig0', b'rig2'])
def test_defined_reference_medium_gamut(profile, tag):
    tags = _tags(profile)
    tags[tag] = _signature(b'prmg')
    PngIccProfile('Gamut vector', _rebuild(profile, tags)).validate_profile_tags()


@pytest.mark.parametrize(
    ('tag', 'value'),
    [
        (b'tech', b'bad!'),
        (b'tech', bytes(4)),
        (b'tech', b'CRT\0'),
        (b'tech', b'LCD\0'),
        (b'tech', b'oled'),
        (b'tech', b'prmg'),
        (b'rig0', b'CRT '),
        (b'rig0', bytes(4)),
        (b'rig0', b'PRMG'),
        (b'rig2', b'CRT '),
        (b'rig2', bytes(4)),
        (b'rig2', b'PRMG'),
    ],
)
def test_undefined_or_wrong_context_signatures_are_rejected(profile, tag, value):
    tags = _tags(profile)
    tags[tag] = _signature(value)
    metadata = PngIccProfile('Wrong signature', _rebuild(profile, tags))
    metadata.validate_profile_structure()  # Directory and signatureType are still sound.
    assert PngIccProfile.from_chunk(metadata.to_chunk()).profile == metadata.profile
    with pytest.raises(PngValidationError, match='signature'):
        metadata.validate_profile_tags()


def test_arbitrary_private_signature_type_remains_opaque(profile):
    tags = _tags(profile)
    tags[b'priv'] = _signature(bytes.fromhex('ff0080fe'))
    PngIccProfile('Private signature', _rebuild(profile, tags)).validate_profile_tags()


def test_v4_signature_tables_are_not_imposed_on_v2_optional_tags(icc_profile_bytes):
    tags = _tags(icc_profile_bytes)
    tags.update({tag: _signature(b'new!') for tag in (b'tech', b'rig0', b'rig2')})
    PngIccProfile('V2 optional data', _rebuild(icc_profile_bytes, tags)).validate_profile_tags()


def test_shared_signature_data_is_checked_in_each_tag_context(profile):
    tags = {b'priv': _signature(b'CRT ')}
    tags.update({tag: data for tag, data in _tags(profile).items() if tag != b'rig0'})
    tags[b'rig0'] = _signature(b'CRT ')
    # Pack one actual element for both entries: content is valid for a private
    # signature, but does not denote the standard perceptual reference gamut.
    groups, table, body = {}, bytearray(), bytearray()
    for tag, data in tags.items():
        if data not in groups:
            groups[data] = 132 + 12 * len(tags) + len(body)
            body.extend(data)
            body.extend(bytes(-len(body) % 4))
        table.extend(pack('>4sII', tag, groups[data], len(data)))
    header = bytearray(profile[:128])
    header[84:100] = bytes(16)
    raw = bytes(header) + pack('>I', len(tags)) + bytes(table) + bytes(body)
    raw = pack('>I', len(raw)) + raw[4:]
    PngIccProfile('Shared data', raw).validate_profile_structure()
    with pytest.raises(PngValidationError, match='gamut signature'):
        PngIccProfile('Shared data', raw).validate_profile_tags()


@pytest.mark.parametrize('tag', [b'tech', b'rig0', b'rig2'])
@pytest.mark.parametrize('representation', ['image', 'document'])
def test_bad_signature_values_are_readable_and_do_not_touch_output(
    profile, tag, representation, png_suite_dir, tmp_path
):
    tags = _tags(profile)
    tags[tag] = _signature(b'bad!')
    profile = _rebuild(profile, tags)
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(PngIccProfile('Inspect invalid signature', profile))
    document = image.to_document()
    raw = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    restored = PngImage.parse(raw)
    assert restored.find_metadata(b'iCCP')[0].profile == profile
    result = restored if representation == 'image' else PngDocument.parse(raw)
    stream = BytesIO(b'unchanged')
    with pytest.raises(PngValidationError, match='signature'):
        result.dump(stream)
    assert stream.getvalue() == b'unchanged'
    target = tmp_path.joinpath('existing.png')
    target.write_bytes(b'unchanged')
    with pytest.raises(PngValidationError, match='signature'):
        result.save(target)
    assert target.read_bytes() == b'unchanged'
