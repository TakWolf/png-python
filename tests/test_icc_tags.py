"""ICC tag checks use official profiles and in-memory mutations of their tags."""

from io import BytesIO
from pathlib import Path
from struct import pack, unpack_from

import pytest

from png import PngDocument, PngIccProfile, PngImage, PngUnsupportedError, PngValidationError


def _tags(profile: bytes) -> dict[bytes, bytes]:
    count, = unpack_from('>I', profile, 128)
    entries = (unpack_from('>4sII', profile, 132 + 12 * index) for index in range(count))
    return {signature: profile[offset:offset + size] for signature, offset, size in entries}


def _rebuild(profile: bytes, tags: dict[bytes, bytes], *, version: int | None = None,
             profile_class: bytes | None = None, color_space: bytes | None = None) -> bytes:
    """Repack a legal directory so each vector isolates tag checks, not bounds."""
    header = bytearray(profile[:128])
    if version is not None:
        header[8] = version
    if profile_class is not None:
        header[12:16] = profile_class
    if color_space is not None:
        header[16:20] = color_space
    entries = []
    body = bytearray()
    offset = 132 + 12 * len(tags)
    for signature, value in tags.items():
        entries.append(pack('>4sII', signature, offset + len(body), len(value)))
        body.extend(value)
        body.extend(bytes(-len(value) % 4))
    result = bytes(header) + pack('>I', len(tags)) + b''.join(entries) + bytes(body)
    return pack('>I', len(result)) + result[4:]


@pytest.fixture
def v4_profile(assets_dir: Path) -> bytes:
    return assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()


@pytest.fixture
def v4_matrix(icc_profile_bytes: bytes, v4_profile: bytes) -> bytes:
    # These are tag/model test vectors, not new certified ICC profiles.
    tags = _tags(icc_profile_bytes)
    localized = _tags(v4_profile)
    tags.update({name: localized[name] for name in (b'desc', b'cprt')})
    return _rebuild(icc_profile_bytes, tags, version=4)


@pytest.mark.parametrize('tag', [b'desc', b'cprt', b'wtpt'])
@pytest.mark.parametrize('version', [2, 4])
def test_icc_common_required_tags(icc_profile_bytes: bytes, v4_profile: bytes, version: int, tag: bytes) -> None:
    profile = icc_profile_bytes if version == 2 else v4_profile
    tags = _tags(profile)
    del tags[tag]
    metadata = PngIccProfile('Missing', _rebuild(profile, tags))
    metadata.validate_profile_structure()  # Directory bounds alone cannot find this.
    with pytest.raises(PngValidationError, match='required tags'):
        metadata.validate_profile_tags()


@pytest.mark.parametrize('profile_class', [b'scnr', b'mntr', b'prtr'])
def test_icc_v4_gray_model_requires_gray_curve(v4_matrix: bytes, profile_class: bytes) -> None:
    tags = _tags(v4_matrix)
    tags[b'kTRC'] = tags[b'rTRC']
    profile = _rebuild(v4_matrix, tags, profile_class=profile_class, color_space=b'GRAY')
    PngIccProfile('Gray model', profile).validate_profile_tags()
    del tags[b'kTRC']
    with pytest.raises(PngValidationError, match='kTRC'):
        PngIccProfile('Missing gray curve', _rebuild(profile, tags)).validate_profile_tags()


@pytest.mark.parametrize('profile_class', [b'scnr', b'mntr'])
def test_icc_v4_matrix_is_an_alternative_to_lut(v4_matrix: bytes, profile_class: bytes) -> None:
    profile = _rebuild(v4_matrix, _tags(v4_matrix), profile_class=profile_class)
    PngIccProfile('Matrix', profile).validate_profile_tags()
    tags = _tags(profile)
    del tags[b'rTRC']
    with pytest.raises(PngValidationError, match='A2B0'):
        PngIccProfile('Incomplete matrix', _rebuild(profile, tags)).validate_profile_tags()
    # A matrix/TRC model requires XYZ PCS; Lab needs a LUT even with all six tags.
    profile = profile[:20] + b'Lab ' + profile[24:]
    with pytest.raises(PngValidationError, match='A2B0'):
        PngIccProfile('Matrix with Lab PCS', profile).validate_profile_tags()


@pytest.mark.parametrize(('profile_class', 'remove', 'missing'), [
    (b'scnr', b'A2B0', 'A2B0'), (b'mntr', b'B2A0', 'B2A0'),
    (b'prtr', b'A2B0', 'gamt'), (b'spac', b'B2A0', 'B2A0'),
    (b'link', b'wtpt', 'pseq'), (b'abst', b'A2B0', 'A2B0'), (b'nmcl', b'A2B0', 'ncl2'),
])
def test_icc_v4_profile_class_required_tags(v4_profile: bytes, profile_class: bytes,
                                          remove: bytes, missing: str) -> None:
    tags = _tags(v4_profile)
    del tags[remove]
    profile = _rebuild(v4_profile, tags, profile_class=profile_class)
    with pytest.raises(PngValidationError, match=missing):
        PngIccProfile('Incomplete class', profile).validate_profile_tags()


@pytest.mark.parametrize(('tag', 'value'), [
    (b'rTRC', b'curv' + bytes(4)),
    (b'rTRC', b'curv' + bytes(4) + pack('>I', 0xFFFFFFFF)),
    (b'rTRC', b'curv' + bytes(4) + pack('>I', 0) + bytes(2)),
    (b'rTRC', b'para' + bytes(4) + pack('>HH', 5, 0)),
    (b'rTRC', b'para' + bytes(4) + pack('>HHI', 0, 1, 65536)),
    (b'rTRC', b'para' + bytes(4) + pack('>HH', 0, 0)),
    (b'wtpt', b'XYZ ' + bytes(4)),
    (b'wtpt', b'text' + bytes(4) + b'white point\0'),
    (b'chad', b'sf32' + bytes(4) + bytes(32)),
    (b'chad', b'XYZ ' + bytes(40)),
    (b'chad', b'sf32' + bytes(40)),
    (b'A2B0', b'XYZ ' + bytes(16)),
    (b'B2A0', b'mAB ' + bytes(28)),
    (b'test', b'XYZ ' + bytes(4) + bytes(13)),
    (b'test', b'sf32' + bytes(5)),
])
def test_icc_key_tag_types_and_counts(v4_matrix: bytes, tag: bytes, value: bytes) -> None:
    tags = _tags(v4_matrix)
    tags[tag] = value
    metadata = PngIccProfile('Malformed tag', _rebuild(v4_matrix, tags))
    metadata.validate_profile_structure()
    with pytest.raises(PngValidationError, match='ICC'):
        metadata.validate_profile_tags()


@pytest.mark.parametrize('count', [0, 1, 2, 1024])
def test_icc_curve_count_encodings(v4_matrix: bytes, count: int) -> None:
    tags = _tags(v4_matrix)
    tags[b'rTRC'] = b'curv' + bytes(4) + pack('>I', count) + pack('>H', 256) * count
    PngIccProfile('Curve', _rebuild(v4_matrix, tags)).validate_profile_tags()


@pytest.mark.parametrize(('function', 'count'), [(0, 1), (1, 3), (2, 4), (3, 5), (4, 7)])
def test_icc_parametric_curve_encodings(v4_matrix: bytes, function: int, count: int) -> None:
    tags = _tags(v4_matrix)
    tags[b'rTRC'] = b'para' + bytes(4) + pack('>HH', function, 0) + pack('>i', 65536) * count
    PngIccProfile('Parametric curve', _rebuild(v4_matrix, tags)).validate_profile_tags()


@pytest.mark.parametrize('damage', [None, 'ascii_count', 'ascii_high_bit', 'ascii_terminator',
                                    'unicode_count', 'unicode_terminator', 'script_count', 'script_terminator'])
def test_icc_v2_description_internal_fields(icc_profile_bytes: bytes, damage: str | None) -> None:
    tags = _tags(icc_profile_bytes)
    # Includes all three strings, with their terminators and the fixed ScriptCode area.
    value = bytearray(b'desc' + bytes(4) + pack('>I', 2) + b'A\0'
                      + pack('>II', 0, 2) + b'\0B\0\0' + pack('>HB', 0, 2) + b'C\0' + bytes(65))
    if damage == 'ascii_count':
        value[8:12] = pack('>I', 0xFFFFFFFF)
    elif damage == 'ascii_high_bit':
        value[12] = 128
    elif damage == 'ascii_terminator':
        value[13] = 65
    elif damage == 'unicode_count':
        value[18:22] = pack('>I', 0xFFFFFFFF)
    elif damage == 'unicode_terminator':
        value[25] = 66
    elif damage == 'script_count':
        value[28] = 68
    elif damage == 'script_terminator':
        value[30] = 67
    tags[b'desc'] = bytes(value)
    if damage is None:
        PngIccProfile('Description', _rebuild(icc_profile_bytes, tags)).validate_profile_tags()
        return
    with pytest.raises(PngValidationError, match='ICC'):
        PngIccProfile('Description', _rebuild(icc_profile_bytes, tags)).validate_profile_tags()


@pytest.mark.parametrize('value', [b'', b'no terminator', b'\x80\0'])
def test_icc_v2_copyright_is_terminated_ascii(icc_profile_bytes: bytes, value: bytes) -> None:
    tags = _tags(icc_profile_bytes)
    tags[b'cprt'] = b'text' + bytes(4) + value
    with pytest.raises(PngValidationError, match='ICC text'):
        PngIccProfile('Copyright', _rebuild(icc_profile_bytes, tags)).validate_profile_tags()


def _localized(*, stride: int = 12) -> bytes:
    # Legal shared string storage and a non-BMP UTF-16 surrogate pair.
    offset = 16 + 2 * stride
    value = 'PNG\U0001f600'.encode('utf-16-be')
    return (b'mluc' + bytes(4) + pack('>II', 2, stride)
            + b'enUS' + pack('>II', len(value), offset) + bytes(stride - 12)
            + b'enGB' + pack('>II', len(value), offset) + bytes(stride - 12) + value)


@pytest.mark.parametrize('stride', [12, 16])
def test_icc_multilingual_shared_strings_and_record_stride(v4_profile: bytes, stride: int) -> None:
    tags = _tags(v4_profile)
    tags[b'desc'] = _localized(stride=stride)
    PngIccProfile('Multilingual', _rebuild(v4_profile, tags)).validate_profile_tags()


@pytest.mark.parametrize('damage', ['header', 'count', 'stride', 'odd_length', 'before_strings',
                                    'outside_tag', 'invalid_utf16'])
def test_icc_multilingual_record_and_string_bounds(v4_profile: bytes, damage: str) -> None:
    tags = _tags(v4_profile)
    value = bytearray(_localized())
    if damage == 'header':
        value = value[:12]
    elif damage == 'count':
        value[8:12] = pack('>I', 0xFFFFFFFF)
    elif damage == 'stride':
        value[12:16] = pack('>I', 11)
    elif damage == 'odd_length':
        value[20:24] = pack('>I', 3)
    elif damage == 'before_strings':
        value[24:28] = pack('>I', 16)
    elif damage == 'outside_tag':
        value[24:28] = pack('>I', 0xFFFFFFFF)
    else:
        value[-2:] = b'\x00A'  # Leaves an unpaired high surrogate.
    tags[b'desc'] = bytes(value)
    metadata = PngIccProfile('Multilingual', _rebuild(v4_profile, tags))
    metadata.validate_profile_structure()
    with pytest.raises(PngValidationError, match='ICC'):
        metadata.validate_profile_tags()


def test_icc_unknown_version_and_class_are_reported_explicitly(v4_profile: bytes) -> None:
    metadata = PngIccProfile('Future version', _rebuild(v4_profile, _tags(v4_profile), version=5))
    metadata.validate_profile_structure()
    with pytest.raises(PngUnsupportedError, match='version 5'):
        metadata.validate_profile_tags()
    metadata.profile = _rebuild(v4_profile, _tags(v4_profile), profile_class=b'????')
    with pytest.raises(PngValidationError, match='profile class'):
        metadata.validate_profile_tags()


@pytest.mark.parametrize('representation', ['image', 'document'])
def test_icc_tag_errors_are_preserved_on_read_but_block_writes(
        png_suite_dir: Path, icc_profile_bytes: bytes, tmp_path: Path, representation: str,
) -> None:
    tags = _tags(icc_profile_bytes)
    del tags[b'wtpt']
    profile = _rebuild(icc_profile_bytes, tags)
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(PngIccProfile('Inspect missing white point', profile))
    document = image.to_document()
    raw = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    result = PngImage.parse(raw) if representation == 'image' else PngDocument.parse(raw)
    assert PngImage.from_document(document).find_metadata(b'iCCP')[0].profile == profile
    stream = BytesIO(b'existing bytes')
    stream.seek(0, 2)
    with pytest.raises(PngValidationError, match='wtpt'):
        result.dump(stream)
    assert stream.getvalue() == b'existing bytes'
    with pytest.raises(PngValidationError, match='wtpt'):
        result.dump_to_bytes()
    target = tmp_path.joinpath('existing.png')
    target.write_bytes(b'existing file')
    with pytest.raises(PngValidationError, match='wtpt'):
        result.save(target)
    assert target.read_bytes() == b'existing file'
    if representation == 'image':
        result.metadata.clear()
    else:
        result.chunks[:] = [chunk for chunk in result.chunks if chunk.type != b'iCCP']
    assert PngImage.parse(result.dump_to_bytes()).bitmap == image.bitmap
