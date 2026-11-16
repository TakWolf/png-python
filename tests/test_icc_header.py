"""ICC header mutations retain official tag payloads and PNG source images."""

from hashlib import md5
from io import BytesIO
from pathlib import Path
from struct import pack

import pytest

from png import PngCicp, PngDocument, PngIccProfile, PngImage, PngValidationError


@pytest.fixture(params=['sRGB2014.icc', 'sRGB_v4_ICC_preference.icc'])
def official_profile(assets_dir: Path, request) -> bytes:
    return assets_dir.joinpath('icc', request.param).read_bytes()


def _change(profile: bytes, offset: int, value: bytes, *, clear_id: bool = True) -> bytes:
    result = bytearray(profile)
    result[offset : offset + len(value)] = value
    if clear_id:
        result[84:100] = bytes(16)
    return bytes(result)


def test_official_profiles_have_valid_present_ids_and_allow_absent_ids(official_profile: bytes) -> None:
    assert any(official_profile[84:100])
    metadata = PngIccProfile('Official', official_profile)
    metadata.validate_profile_tags()
    metadata.profile = _change(official_profile, 84, bytes(16))
    metadata.validate_profile_tags()
    assert metadata.profile == official_profile[:84] + bytes(16) + official_profile[100:]


@pytest.mark.parametrize(
    ('offset', 'value', 'message'),
    [
        (9, b'\xa0', 'version'),
        (9, b'\x0a', 'version'),
        (10, b'\0\x01', 'version'),
        (10, b'\x01\0', 'version'),
        (20, b'RGB ', 'PCS must'),
        (20, bytes(4), 'PCS must'),
        (26, pack('>H', 0), 'date/time'),
        (26, pack('>H', 13), 'date/time'),
        (28, pack('>H', 0), 'date/time'),
        (28, pack('>H', 32), 'date/time'),
        (30, pack('>H', 24), 'date/time'),
        (32, pack('>H', 60), 'date/time'),
        (34, pack('>H', 60), 'date/time'),
        (64, pack('>I', 4), 'rendering intent'),
        (64, pack('>I', 65536), 'rendering intent'),
        (68, pack('>i', 0), 'illuminant'),
        (72, pack('>i', -65536), 'illuminant'),
        (76, pack('>i', 54000), 'illuminant'),
        (100, b'\x01', 'reserved bytes'),
        (127, b'\x01', 'reserved bytes'),
    ],
)
def test_icc_header_field_ranges(official_profile: bytes, offset: int, value: bytes, message: str) -> None:
    metadata = PngIccProfile('Header mutation', _change(official_profile, offset, value))
    metadata.validate_profile_structure()
    metadata.validate()  # Basic inspection does not certify the opaque profile.
    with pytest.raises(PngValidationError, match=message):
        metadata.validate_profile_tags()


@pytest.mark.parametrize('version', [b'\x90', b'\x09', b'\x99'])
def test_unknown_bcd_minor_versions_remain_compatible(official_profile: bytes, version: bytes) -> None:
    PngIccProfile('Compatible minor', _change(official_profile, 9, version)).validate_profile_tags()


@pytest.mark.parametrize('year', [0, 9999, 10000, 65535])
def test_icc_year_uses_the_specification_uint16_range(official_profile: bytes, year: int) -> None:
    PngIccProfile('Year', _change(official_profile, 24, pack('>H', year))).validate_profile_tags()


@pytest.mark.parametrize('intent', [0, 1, 2, 3])
def test_profile_id_ignores_flags_and_rendering_intent(official_profile: bytes, intent: int) -> None:
    profile = _change(official_profile, 44, pack('>I', 0x80000003), clear_id=False)
    profile = _change(profile, 64, pack('>I', intent), clear_id=False)
    assert profile[84:100] == official_profile[84:100]
    PngIccProfile('Embedding flags', profile).validate_profile_tags()


def test_profile_id_covers_payload_without_mutating_the_profile(official_profile: bytes) -> None:
    # A preferred-CMM change leaves the directory and known tag contents intact.
    changed = _change(official_profile, 4, b'lcms', clear_id=False)
    metadata = PngIccProfile('Stale ID', changed)
    with pytest.raises(PngValidationError, match='Profile ID'):
        metadata.validate_profile_tags()
    assert metadata.profile == changed
    # Independent copy-based calculation, following the three excluded fields.
    calculation = bytearray(changed)
    calculation[44:48] = bytes(4)
    calculation[64:68] = bytes(4)
    calculation[84:100] = bytes(16)
    repaired = _change(changed, 84, md5(calculation, usedforsecurity=False).digest(), clear_id=False)
    metadata.profile = repaired
    metadata.validate_profile_tags()
    assert metadata.profile == repaired


@pytest.mark.parametrize('bit', [4, 15, 31])
def test_v4_reserved_device_attribute_bits(assets_dir: Path, bit: int) -> None:
    profile = assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()
    metadata = PngIccProfile('Reserved attribute', _change(profile, 56, pack('>Q', 1 << bit)))
    with pytest.raises(PngValidationError, match='attribute reserved bits'):
        metadata.validate_profile_tags()


def test_v4_device_attribute_vendor_bits_are_preserved(assets_dir: Path) -> None:
    profile = assets_dir.joinpath('icc', 'sRGB_v4_ICC_preference.icc').read_bytes()
    value = pack('>Q', 0xA5A5A5A50000000F)
    changed = _change(profile, 56, value)
    metadata = PngIccProfile('Vendor attributes', changed)
    metadata.validate_profile_tags()
    assert metadata.profile[56:64] == value


@pytest.mark.parametrize(
    ('offset', 'values'), [(68, [63187, 63190, 63193]), (72, [65533, 65536, 65539]), (76, [54058, 54061, 54063])]
)
def test_d50_is_checked_after_rounding_not_as_a_single_binary_value(
    official_profile: bytes,
    offset: int,
    values: list[int],
) -> None:
    for value in values:
        metadata = PngIccProfile('Rounded D50', _change(official_profile, offset, pack('>i', value)))
        metadata.validate_profile_tags()


@pytest.mark.parametrize(
    ('offset', 'value'), [(68, 63186), (68, 63194), (72, 65532), (72, 65540), (76, 54057), (76, 54064)]
)
def test_d50_rejects_values_just_outside_the_rounding_interval(
    official_profile: bytes,
    offset: int,
    value: int,
) -> None:
    metadata = PngIccProfile('Outside D50', _change(official_profile, offset, pack('>i', value)))
    with pytest.raises(PngValidationError, match='illuminant must round'):
        metadata.validate_profile_tags()


@pytest.mark.parametrize('profile_class', [b'link', b'abst'])
@pytest.mark.parametrize('representation', ['image', 'document'])
def test_nonembeddable_profile_classes_are_preserved_on_read_but_not_written(
    icc_profile_bytes: bytes,
    png_suite_dir: Path,
    tmp_path: Path,
    profile_class: bytes,
    representation: str,
) -> None:
    profile = _change(icc_profile_bytes, 12, profile_class)
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.extend([PngCicp(1, 13, 0, 1), PngIccProfile('Class mutation', profile)])
    document = image.to_document()
    raw = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    restored = PngImage.parse(raw)
    assert restored.find_metadata(b'iCCP')[0].profile == profile
    result = restored if representation == 'image' else PngDocument.parse(raw)
    stream = BytesIO(b'unchanged')
    with pytest.raises(PngValidationError, match='cannot be embedded'):
        result.dump(stream)
    assert stream.getvalue() == b'unchanged'
    target = tmp_path.joinpath('existing.png')
    target.write_bytes(b'unchanged')
    with pytest.raises(PngValidationError, match='cannot be embedded'):
        result.save(target)
    assert target.read_bytes() == b'unchanged'


@pytest.mark.parametrize('representation', ['image', 'document'])
def test_stale_profile_id_is_preserved_on_read_but_not_written(
    official_profile: bytes,
    png_suite_dir: Path,
    tmp_path: Path,
    representation: str,
) -> None:
    profile = _change(official_profile, 4, b'lcms', clear_id=False)
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(PngIccProfile('Stale ID', profile))
    document = image.to_document()
    raw = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    restored = PngImage.parse(raw)
    assert restored.find_metadata(b'iCCP')[0].profile == profile
    result = restored if representation == 'image' else PngDocument.parse(raw)
    target = tmp_path.joinpath('existing.png')
    target.write_bytes(b'unchanged')
    with pytest.raises(PngValidationError, match='Profile ID'):
        result.save(target)
    assert target.read_bytes() == b'unchanged'
