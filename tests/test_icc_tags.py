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
    header[84:100] = bytes(16)  # Repacked vectors no longer have the original Profile ID.
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
    for name in (b'dmnd', b'dmdd', b'vued'):
        if name in tags:
            tags[name] = localized[b'desc']
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
    profile = _rebuild(v4_profile, tags, profile_class=profile_class,
                       color_space=b'XYZ ' if profile_class == b'abst' else b'RGB ')
    with pytest.raises(PngValidationError, match=missing):
        PngIccProfile('Incomplete class', profile).validate_profile_tags()


_MATRIX_TAGS = (b'rXYZ', b'gXYZ', b'bXYZ', b'rTRC', b'gTRC', b'bTRC')
_TRANSFORM_TAGS = (b'A2B0', b'A2B1', b'A2B2', b'B2A0', b'B2A1', b'B2A2')


def _lut16(inputs: int = 3, outputs: int = 3) -> bytes:
    """A layout vector with two entries per table/grid dimension, not a certified transform."""
    identity = pack('>9i', 65536, 0, 0, 0, 65536, 0, 0, 0, 65536)
    return (b'mft2' + bytes(4) + bytes((inputs, outputs, 2, 0)) + identity + pack('>HH', 2, 2)
            + bytes(4 * inputs + 2 * 2 ** inputs * outputs + 4 * outputs))


@pytest.mark.parametrize('profile_class', [b'scnr', b'mntr', b'prtr'])
@pytest.mark.parametrize('optional_luts', [False, True])
def test_icc_v2_gray_requires_curve_even_with_optional_luts(
        gray_icc_profile_bytes: bytes, profile_class: bytes, optional_luts: bool,
) -> None:
    tags = _tags(gray_icc_profile_bytes)
    if optional_luts:
        tags[b'A2B0'] = _lut16(1, 3)
        tags[b'B2A0'] = _lut16(3, 1)
    profile = _rebuild(gray_icc_profile_bytes, tags, profile_class=profile_class)
    PngIccProfile('Gray tag model', profile).validate_profile_tags()
    del tags[b'kTRC']
    with pytest.raises(PngValidationError, match='kTRC'):
        PngIccProfile('Missing gray curve', _rebuild(profile, tags)).validate_profile_tags()


@pytest.mark.parametrize('missing', _MATRIX_TAGS)
def test_icc_v2_display_requires_each_matrix_tag(icc_profile_bytes: bytes, missing: bytes) -> None:
    tags = _tags(icc_profile_bytes)
    tags.update({b'A2B0': _lut16(), b'B2A0': _lut16()})
    del tags[missing]
    with pytest.raises(PngValidationError, match=missing.decode()):
        PngIccProfile('Incomplete v2 display', _rebuild(icc_profile_bytes, tags)).validate_profile_tags()


def test_icc_v2_and_v4_display_lut_models_have_different_requirements(
        icc_profile_bytes: bytes, v4_matrix: bytes,
) -> None:
    for profile in (icc_profile_bytes, v4_matrix):
        tags = {name: value for name, value in _tags(profile).items() if name not in _MATRIX_TAGS}
        tags.update({b'A2B0': _lut16(), b'B2A0': _lut16()})
        metadata = PngIccProfile('LUT display', _rebuild(profile, tags))
        if profile[8] == 2:
            with pytest.raises(PngValidationError, match='rTRC'):
                metadata.validate_profile_tags()
        else:
            metadata.validate_profile_tags()


@pytest.mark.parametrize('tag', _TRANSFORM_TAGS)
def test_icc_v2_lab_display_needs_a_multidimensional_transform(icc_profile_bytes: bytes, tag: bytes) -> None:
    profile = icc_profile_bytes[:20] + b'Lab ' + icc_profile_bytes[24:]
    tags = _tags(profile)
    without_lut = PngIccProfile('Lab display without LUT', _rebuild(profile, tags))
    with pytest.raises(PngValidationError, match='Lab display requires'):
        without_lut.validate_profile_tags()
    tags[tag] = _lut16()
    PngIccProfile('Lab display with LUT', _rebuild(profile, tags)).validate_profile_tags()


@pytest.mark.parametrize('lab_pcs', [False, True])
def test_icc_v2_input_supports_matrix_or_lut(icc_profile_bytes: bytes, lab_pcs: bool) -> None:
    profile = icc_profile_bytes
    if lab_pcs:
        profile = profile[:20] + b'Lab ' + profile[24:]
    tags = _tags(profile)
    metadata = PngIccProfile('Input matrix', _rebuild(profile, tags, profile_class=b'scnr'))
    if lab_pcs:
        with pytest.raises(PngValidationError, match='A2B0'):
            metadata.validate_profile_tags()
    else:
        metadata.validate_profile_tags()
    tags = {name: value for name, value in tags.items() if name not in _MATRIX_TAGS}
    tags[b'A2B0'] = _lut16()
    metadata.profile = _rebuild(profile, tags, profile_class=b'scnr')
    metadata.validate_profile_tags()
    del tags[b'A2B0']
    with pytest.raises(PngValidationError, match='A2B0'):
        PngIccProfile('Missing input model', _rebuild(profile, tags, profile_class=b'scnr')).validate_profile_tags()


@pytest.mark.parametrize('missing', _TRANSFORM_TAGS + (b'gamt',))
def test_icc_v2_color_output_requires_all_intents_and_gamut(icc_profile_bytes: bytes, missing: bytes) -> None:
    tags = _tags(icc_profile_bytes)
    tags.update({name: _lut16() for name in _TRANSFORM_TAGS})
    tags[b'gamt'] = _lut16(3, 1)
    profile = _rebuild(icc_profile_bytes, tags, profile_class=b'prtr')
    PngIccProfile('Output tag model', profile).validate_profile_tags()
    del tags[missing]
    with pytest.raises(PngValidationError, match=missing.decode()):
        PngIccProfile('Missing output tag', _rebuild(profile, tags)).validate_profile_tags()


@pytest.mark.parametrize(('profile_class', 'missing'), [(b'link', 'pseq'), (b'abst', 'A2B0'), (b'nmcl', 'ncl2')])
def test_icc_v2_additional_class_required_tags(icc_profile_bytes: bytes, profile_class: bytes, missing: str) -> None:
    profile = _rebuild(icc_profile_bytes, _tags(icc_profile_bytes), profile_class=profile_class,
                       color_space=b'XYZ ' if profile_class == b'abst' else b'RGB ')
    with pytest.raises(PngValidationError, match=missing):
        PngIccProfile('Incomplete additional class', profile).validate_profile_tags()


@pytest.mark.parametrize('missing', [b'A2B0', b'B2A0'])
def test_icc_v2_colorspace_requires_both_directions(icc_profile_bytes: bytes, missing: bytes) -> None:
    tags = _tags(icc_profile_bytes)
    tags.update({b'A2B0': _lut16(), b'B2A0': _lut16()})
    profile = _rebuild(icc_profile_bytes, tags, profile_class=b'spac')
    PngIccProfile('ColorSpace tag model', profile).validate_profile_tags()
    del tags[missing]
    with pytest.raises(PngValidationError, match=missing.decode()):
        PngIccProfile('Missing ColorSpace direction', _rebuild(profile, tags)).validate_profile_tags()


@pytest.mark.parametrize('representation', ['image', 'document'])
def test_icc_v2_missing_model_is_retained_on_read_and_blocks_output(
        png_suite_dir: Path, gray_icc_profile_bytes: bytes, tmp_path: Path, representation: str,
) -> None:
    tags = _tags(gray_icc_profile_bytes)
    del tags[b'kTRC']
    profile = _rebuild(gray_icc_profile_bytes, tags)
    image = PngImage.load(png_suite_dir.joinpath('basn0g08.png'))
    image.metadata.append(PngIccProfile('Incomplete gray model', profile))
    document = image.to_document()
    raw = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    restored = PngImage.parse(raw)
    assert restored.find_metadata(b'iCCP')[0].profile == profile
    result = restored if representation == 'image' else PngDocument.parse(raw)
    stream = BytesIO(b'unchanged')
    with pytest.raises(PngValidationError, match='kTRC'):
        result.dump(stream)
    assert stream.getvalue() == b'unchanged'
    target = tmp_path.joinpath('existing.png')
    target.write_bytes(b'unchanged')
    with pytest.raises(PngValidationError, match='kTRC'):
        result.save(target)
    assert target.read_bytes() == b'unchanged'


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
