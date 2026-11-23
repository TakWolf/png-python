import zlib
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from struct import pack

import pytest

from png import (
    PngChunk,
    PngCicp,
    PngColorType,
    PngDocument,
    PngHeader,
    PngIccProfile,
    PngImage,
    PngLimitError,
    PngParseError,
    PngReadLimits,
    PngSrgb,
    PngValidationError,
)


def _icc_with_space(profile: bytes, signature: bytes) -> bytes:
    return profile[:16] + signature + profile[20:84] + bytes(16) + profile[100:]


def _wire_bytes(document: PngDocument) -> bytes:
    """Serialize intentionally invalid documents without bypassing chunk CRCs."""
    return b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)


@pytest.mark.parametrize('load', [PngDocument.load, PngImage.load])
@pytest.mark.parametrize('tail', [b'\0', b'\n', b'not PNG data', bytes.fromhex('0000000049454e44ae426082')])
def test_file_load_rejects_every_kind_of_content_after_iend(
    png_suite_dir: Path,
    tmp_path: Path,
    load,
    tail: bytes,
) -> None:
    data = png_suite_dir.joinpath('basn2c08.png').read_bytes()
    path = tmp_path.joinpath('trailing-content.png')
    path.write_bytes(data + tail)
    with pytest.raises(PngParseError, match='after IEND'):
        load(path)
    # The data-byte policy describes one PNG. Trailing file content is a format error.
    with pytest.raises(PngParseError, match='after IEND') as caught:
        load(path, limits=PngReadLimits(max_total_bytes=len(data)))
    assert not isinstance(caught.value, PngLimitError)


def test_file_load_rejects_concatenated_pngs_but_stream_parse_can_read_them(
    png_suite_dir: Path,
    tmp_path: Path,
) -> None:
    first = png_suite_dir.joinpath('basn2c08.png').read_bytes()
    second = png_suite_dir.joinpath('basn0g01.png').read_bytes()
    path = tmp_path.joinpath('two-images.png')
    path.write_bytes(first + second)
    with pytest.raises(PngParseError, match='after IEND'):
        PngDocument.load(path)
    with pytest.raises(PngParseError, match='after IEND'):
        PngImage.load(path)
    stream = BytesIO(b'prefix' + first + second + b'suffix')
    stream.seek(6)
    assert PngDocument.parse(stream).dump_to_bytes() == first
    assert stream.tell() == 6 + len(first)
    image = PngImage.parse(stream)
    assert image.header.color_type == PngColorType.GRAYSCALE
    assert stream.read() == b'suffix'
    assert not stream.closed
    # Bytes input has the same one-datastream framing contract as a binary stream.
    assert PngDocument.parse(first + second).dump_to_bytes() == first


def test_whole_file_boundary_is_checked_before_pixel_decoding(png_suite_dir: Path, tmp_path: Path, monkeypatch) -> None:
    path = tmp_path.joinpath('trailing.png')
    path.write_bytes(png_suite_dir.joinpath('basn6a16.png').read_bytes() + b'\0')

    def unexpected_decode(*args, **kwargs):
        pytest.fail('a file with trailing data must be rejected before pixel decoding')

    monkeypatch.setattr('png.image.decode_pixels', unexpected_decode)
    with pytest.raises(PngParseError, match='after IEND'):
        PngImage.load(path)


def test_valid_file_and_all_zero_iend_crc_still_report_original_error(
    png_suite_dir: Path,
    tmp_path: Path,
) -> None:
    data = png_suite_dir.joinpath('basn2c08.png').read_bytes()
    path = tmp_path.joinpath('image.png')
    path.write_bytes(data)
    assert PngDocument.load(path).dump_to_bytes() == data
    assert PngImage.load(path).bitmap == PngImage.parse(data).bitmap
    path.write_bytes(data[:-4] + bytes(4) + b'tail')
    with pytest.raises(PngParseError, match='CRC mismatch'):
        PngImage.load(path)


@pytest.mark.parametrize(
    'name',
    [
        'basn0g01.png',
        'basn0g16.png',
        'basn4a08.png',
        'basn4a16.png',
        'basn2c08.png',
        'basn2c16.png',
        'basn3p01.png',
        'basn3p08.png',
        'basn6a08.png',
        'basn6a16.png',
    ],
)
def test_icc_data_space_matches_all_png_color_types(
    png_suite_dir: Path,
    icc_profile_bytes: bytes,
    gray_icc_profile_bytes: bytes,
    name: str,
) -> None:
    image = PngImage.load(png_suite_dir.joinpath(name))
    gray = image.header.color_type in (PngColorType.GRAYSCALE, PngColorType.GRAYSCALE_ALPHA)
    signature = b'GRAY' if gray else b'RGB '
    profile = PngIccProfile('Fixture', gray_icc_profile_bytes if gray else icc_profile_bytes)
    image.metadata.append(profile)
    image.validate()
    restored = PngImage.parse(image.dump_to_bytes())
    assert restored.bitmap == image.bitmap
    assert restored.find_metadata(b'iCCP')[0].color_space == signature
    assert restored.find_metadata(b'iCCP')[0].profile == profile.profile
    profile.profile = _icc_with_space(profile.profile, b'RGB ' if gray else b'GRAY')
    with pytest.raises(PngValidationError, match='color space must match'):
        image.validate()


@pytest.mark.parametrize('as_raw', [False, True])
def test_raw_and_structured_icc_use_the_same_context_checks(icc_profile_bytes: bytes, as_raw: bool) -> None:
    profile = PngIccProfile('RGB', icc_profile_bytes)
    image = PngImage(PngHeader((1, 1), color_type=PngColorType.GRAYSCALE), [[0]])
    if as_raw:
        image.ancillary_chunks.append(profile.to_chunk())
    else:
        image.metadata.append(profile)
    with pytest.raises(PngValidationError, match='color space must match'):
        image.validate()


def test_document_checks_icc_context_before_pixels_and_preserves_parse_error_type(
    png_suite_dir: Path,
    icc_profile_bytes: bytes,
    monkeypatch,
) -> None:
    document = PngDocument.load(png_suite_dir.joinpath('basn0g08.png'))
    document.chunks.insert(1, PngIccProfile('RGB', icc_profile_bytes).to_chunk())
    with pytest.raises(PngValidationError, match='color space must match'):
        document.validate()
    with pytest.raises(PngParseError, match='color space must match'):
        PngDocument.parse(_wire_bytes(document))

    def unexpected_decode(*args, **kwargs):
        pytest.fail('mismatched ICC data space must be rejected before decoding')

    monkeypatch.setattr('png.image.decode_pixels', unexpected_decode)
    with pytest.raises(PngValidationError, match='color space must match'):
        PngImage.from_document(document)


def test_higher_color_precedence_does_not_waive_icc_color_type_requirement(
    png_suite_dir: Path,
    icc_profile_bytes: bytes,
) -> None:
    image = PngImage.load(png_suite_dir.joinpath('basn6a08.png'))
    image.metadata = [PngCicp(1, 13), PngSrgb(), PngIccProfile('Wrong', _icc_with_space(icc_profile_bytes, b'GRAY'))]
    with pytest.raises(PngValidationError, match='color space must match'):
        image.validate()


@pytest.mark.parametrize('size', [0, 4, 20, 36, 40, 127])
def test_icc_header_cannot_be_truncated(icc_profile_bytes: bytes, size: int) -> None:
    value = PngIccProfile('Truncated', icc_profile_bytes[:size])
    with pytest.raises(PngValidationError, match='128-byte header'):
        value.validate()
    payload = b'K\0\0' + zlib.compress(value.profile)
    with pytest.raises(PngValidationError, match='128-byte header'):
        PngIccProfile.from_chunk(PngChunk(b'iCCP', payload))


@pytest.mark.parametrize('signature', [b'\0\0\0\0', b'ACSP', b'bad!'])
def test_icc_header_requires_profile_file_signature(icc_profile_bytes: bytes, signature: bytes) -> None:
    profile = icc_profile_bytes[:36] + signature + icc_profile_bytes[40:]
    with pytest.raises(PngValidationError, match='acsp'):
        PngIccProfile('Invalid', profile).validate()


@pytest.mark.parametrize('signature', [b'CMYK', b'Lab ', b'XYZ ', b'YCbr', b'\0\0\0\0'])
def test_png_cannot_embed_other_icc_data_color_spaces(icc_profile_bytes: bytes, signature: bytes) -> None:
    with pytest.raises(PngValidationError, match='RGB or grayscale'):
        PngIccProfile('Other', _icc_with_space(icc_profile_bytes, signature)).to_chunk()


def test_icc_header_properties_derive_from_current_payload(truncated_icc_profile_bytes: bytes) -> None:
    profile = PngIccProfile('Original', truncated_icc_profile_bytes)
    assert profile.color_space == b'RGB '
    assert profile.declared_size == 2992
    assert len(profile.profile) == 2988
    clone = deepcopy(profile)
    clone.profile = pack('>I', 12345) + _icc_with_space(clone.profile, b'GRAY')[4:]
    assert clone.color_space == b'GRAY'
    assert clone.declared_size == 12345
    assert profile.color_space == b'RGB '
    assert profile.declared_size == 2992


def test_wpt_truncated_inner_icc_is_preserved_for_inspection_but_not_written(
    wpt_png_dir: Path,
    truncated_icc_profile_bytes: bytes,
) -> None:
    # The final chad entry ends at 2992, four bytes beyond this WPT payload.
    # Reading keeps the original bytes; the writer must not silently repair them.
    document = PngDocument.load(wpt_png_dir.joinpath('cICP-and-iCCP.png'))
    image = PngImage.from_document(document)
    (profile,) = image.find_metadata(b'iCCP')
    assert profile.profile == truncated_icc_profile_bytes
    assert profile.declared_size - len(profile.profile) == 4
    with pytest.raises(PngValidationError, match='ICC declared size'):
        image.dump_to_bytes()
    with pytest.raises(PngValidationError, match='ICC declared size'):
        document.dump_to_bytes()
    assert image.find_metadata(b'iCCP')[0].profile == truncated_icc_profile_bytes


def test_gray_icc_is_not_silently_attached_to_rgb_composite(icc_profile_bytes: bytes) -> None:
    profile = PngIccProfile('Gray header', _icc_with_space(icc_profile_bytes, b'GRAY'))
    image = PngImage(PngHeader((1, 1), color_type=PngColorType.GRAYSCALE), [[128]], metadata=[profile])
    rendered = next(image.render_frames()).image
    assert rendered.header.color_type == PngColorType.TRUECOLOR_ALPHA
    assert rendered.find_metadata(b'iCCP') == []
    assert image.find_metadata(b'iCCP')[0] is profile
