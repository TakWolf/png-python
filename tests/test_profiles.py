from io import BytesIO
import hashlib
import json
from pathlib import Path
from struct import pack, unpack_from

import pytest

from png import (
    PngDocument, PngExif, PngIccProfile, PngImage, PngUnsupportedError, PngValidationError,
)


def _replace(data: bytes, offset: int, value: int, endian: str = '>') -> bytes:
    return data[:offset] + pack(endian + 'I', value) + data[offset + 4:]


def _icc(entries: list[tuple[bytes, int, int]], body: bytes, version: int = 4) -> bytes:
    """Structural vectors only; these are not complete colorimetric profiles."""
    header = bytearray(128)
    header[8] = version
    header[16:20] = b'RGB '
    header[36:40] = b'acsp'
    data = bytes(header) + pack('>I', len(entries)) + b''.join(pack('>4sII', *entry) for entry in entries) + body
    return _replace(data, 0, len(data))


def _tiff(entries: list[tuple[int, int, int, bytes]], *, endian: str = '>', following: int = 0, tail: bytes = b'') -> bytes:
    magic = b'MM\0*' if endian == '>' else b'II*\0'
    return magic + pack(endian + 'IH', 8, len(entries)) + b''.join(
        pack(endian + 'HHI', tag, kind, count) + value for tag, kind, count, value in entries
    ) + pack(endian + 'I', following) + tail


@pytest.mark.parametrize('name', ['sRGB2014.icc', 'sRGB_v4_ICC_preference.icc'])
def test_official_icc_profiles_pass_and_embed_without_rewriting(assets_dir: Path, png_suite_dir: Path, name: str) -> None:
    original = assets_dir.joinpath('icc', name).read_bytes()
    metadata = PngIccProfile('Official ICC', original)
    metadata.validate_profile_structure()
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(metadata)
    restored = PngImage.parse(image.dump_to_bytes())
    assert restored.find_metadata(b'iCCP')[0].profile == original
    assert restored.bitmap == image.bitmap


def test_icc_asset_provenance_and_embedded_identification(assets_dir: Path) -> None:
    directory = assets_dir.joinpath('icc')
    manifest = json.loads(directory.joinpath('SOURCE.json').read_text())
    assert [record['size'] for record in manifest['files']] == [3024, 60960]
    for record in manifest['files']:
        data = directory.joinpath(record['path']).read_bytes()
        assert len(data) == record['size']
        assert hashlib.sha256(data).hexdigest() == record['sha256']
        assert data[36:40] == b'acsp'
        assert b'cprt' in data[132:132 + 12 * unpack_from('>I', data, 128)[0]]
    assert 'International Color Consortium' in directory.joinpath('LICENSE.txt').read_text()


@pytest.mark.parametrize('damage', ['truncated', 'declared', 'table_count', 'table_offset', 'alignment',
                                    'tag_extent', 'short_type', 'duplicate_tag', 'reserved_type'])
def test_invalid_icc_structure_fields_are_rejected(icc_profile_bytes: bytes, damage: str) -> None:
    data = icc_profile_bytes
    if damage == 'truncated':
        data = data[:-1]
    elif damage == 'declared':
        data = _replace(data, 0, len(data) + 4)
    elif damage == 'table_count':
        data = _replace(data, 128, 0xFFFFFFFF)
    elif damage == 'table_offset':
        data = _replace(data, 136, 128)
    elif damage == 'alignment':
        data = _replace(data, 136, 325)
    elif damage == 'tag_extent':
        data = _replace(data, 140, 0xFFFFFFFF)
    elif damage == 'short_type':
        data = _replace(data, 140, 7)
    elif damage == 'duplicate_tag':
        data = data[:144] + data[132:136] + data[148:]
    else:
        offset, = unpack_from('>I', data, 136)
        data = data[:offset + 4] + b'BAD!' + data[offset + 8:]
    # Envelope/header inspection can retain the original opaque payload.
    metadata = PngIccProfile('Inspect', data)
    assert PngIccProfile.from_chunk(metadata.to_chunk()).profile == data
    with pytest.raises(PngValidationError, match='ICC'):
        metadata.validate_profile_structure()


def test_shared_icc_tag_data_is_legal_but_partial_overlap_is_not() -> None:
    shared = _icc([(b'a001', 156, 8), (b'a002', 156, 8)], b'text' + bytes(4))
    PngIccProfile('Shared', shared).validate_profile_structure()
    # Same offset with a different size is not aliasing an entire element.
    overlap = _icc([(b'a001', 156, 8), (b'a002', 156, 12)], b'text' + bytes(8))
    with pytest.raises(PngValidationError, match='overlap'):
        PngIccProfile('Overlap', overlap).validate_profile_structure()


@pytest.mark.parametrize('body', [b'text' + bytes(4) + b'A\0\0X', b'text' + bytes(4) + b'A\0' + bytes(6)])
def test_icc_v4_padding_and_unreferenced_tail_are_rejected(body: bytes) -> None:
    data = _icc([(b'a001', 144, 10)], body)
    with pytest.raises(PngValidationError, match='ICC v4'):
        PngIccProfile('Padding', data).validate_profile_structure()


def test_icc_v2_does_not_inherit_v4_only_contiguity_constraints() -> None:
    # Only v4's explicit packing rules are applied to v4; v2 checks still cover bounds.
    data = _icc([(b'a001', 148, 8)], bytes(4) + b'text' + bytes(4), version=2)
    PngIccProfile('V2 layout', data).validate_profile_structure()


@pytest.mark.parametrize('endian', ['>', '<'])
def test_tiff_inline_and_external_fields_use_the_profile_byte_order(endian: str) -> None:
    inline = pack(endian + 'H', 6) + bytes(2)
    data = _tiff([(0x0112, 3, 1, inline), (0x011A, 5, 1, pack(endian + 'I', 38))],
                 endian=endian, tail=pack(endian + 'II', 72, 1))
    metadata = PngExif(data)
    metadata.validate_profile_structure()
    assert PngExif.from_chunk(metadata.to_chunk()).profile == data


@pytest.mark.parametrize('damage', ['header', 'zero_ifd', 'before_header', 'odd_ifd', 'outside_ifd',
                                    'zero_count', 'table_count', 'next_pointer', 'cycle', 'external_extent',
                                    'external_alignment', 'external_count', 'sub_ifd', 'sub_ifd_type', 'sub_ifd_cycle'])
def test_invalid_tiff_directory_and_value_bounds_are_rejected(damage: str) -> None:
    data = _tiff([(0x011A, 5, 1, pack('>I', 26))], tail=pack('>II', 72, 1))
    if damage == 'header':
        data = data[:4]
    elif damage == 'zero_ifd':
        data = _replace(data, 4, 0)
    elif damage == 'before_header':
        data = _replace(data, 4, 4)
    elif damage == 'odd_ifd':
        data = _replace(data, 4, 9)
    elif damage == 'outside_ifd':
        data = _replace(data, 4, 0xFFFFFFFE)
    elif damage == 'zero_count':
        data = data[:8] + bytes(2) + data[10:]
    elif damage == 'table_count':
        data = data[:8] + b'\xff\xff' + data[10:]
    elif damage == 'next_pointer':
        data = data[:25]
    elif damage == 'cycle':
        data = _replace(data, 22, 8)
    elif damage == 'external_extent':
        data = _replace(data, 18, 0xFFFFFFFE)
    elif damage == 'external_alignment':
        data = _replace(data, 18, 27)
    elif damage == 'external_count':
        data = _replace(data, 14, 0xFFFFFFFF)
    elif damage == 'sub_ifd':
        data = _tiff([(0x8769, 4, 1, pack('>I', 0xFFFFFFFE))])
    elif damage == 'sub_ifd_type':
        data = _tiff([(0x8825, 3, 1, pack('>I', 26))])
    else:
        data = _tiff([(0xA005, 4, 1, pack('>I', 8))])
    metadata = PngExif(data)
    metadata.validate()  # Existing envelope-only inspection stays available.
    with pytest.raises(PngValidationError, match='Exif'):
        metadata.validate_profile_structure()


@pytest.mark.parametrize('tags', [[0x0112, 0x0100], [0x0112, 0x0112]])
def test_ifd_entries_must_be_sorted_and_unique(tags: list[int]) -> None:
    data = _tiff([(tag, 3, 1, b'\0\x01\0\0') for tag in tags])
    with pytest.raises(PngValidationError, match='sorted'):
        PngExif(data).validate_profile_structure()


def test_sub_ifd_sharing_and_opaque_maker_note_data() -> None:
    data = _tiff([(0x8769, 4, 1, pack('>I', 38)), (0x8825, 4, 1, pack('>I', 38))],
                 tail=pack('>HHHI4sI', 1, 0x0112, 3, 1, b'\0\x01\0\0', 0))
    PngExif(data).validate_profile_structure()
    private = _tiff([(0x927C, 7, 6, pack('>I', 26))], tail=b'\xff' * 6)
    PngExif(private).validate_profile_structure()  # Never interpret MakerNote contents as pointers.


@pytest.mark.parametrize('tag', [0x8769, 0x8825, 0xA005])
def test_null_optional_directory_pointer_is_not_dereferenced(tag: int) -> None:
    # Checking the pointer's extent does not assert whether that directory is
    # required by a particular Exif profile or tag combination.
    PngExif(_tiff([(tag, 4, 1, bytes(4))])).validate_profile_structure()


def test_deep_tiff_ifd_chains_do_not_use_python_recursion() -> None:
    directories = []
    for index in range(1100):
        following = 8 + (index + 1) * 18 if index < 1099 else 0
        directories.append(pack('>HHHI4sI', 1, 0x0112, 3, 1, b'\0\x01\0\0', following))
    data = b'MM\0*' + pack('>I', 8) + b''.join(directories)
    PngExif(data).validate_profile_structure()


@pytest.mark.parametrize('damage', ['missing_length', 'zero_length', 'outside', 'odd'])
def test_jpeg_thumbnail_extent_is_checked_without_decoding_jpeg(damage: str) -> None:
    entries = [(0x0201, 4, 1, pack('>I', 38))]
    if damage != 'missing_length':
        entries.append((0x0202, 4, 1, pack('>I', 0 if damage == 'zero_length' else 8)))
    if damage == 'odd':
        entries[0] = (0x0201, 4, 1, pack('>I', 39))
    data = _tiff(entries, tail=b'\xff\xd8\xff\xd9')
    with pytest.raises(PngValidationError, match='Exif'):
        PngExif(data).validate_profile_structure()
    valid = _tiff([(0x0201, 4, 1, pack('>I', 38)), (0x0202, 4, 1, pack('>I', 4))],
                  tail=b'\xff\xd8\xff\xd9')
    PngExif(valid).validate_profile_structure()


def test_unknown_tiff_field_type_is_preserved_but_structural_check_is_unsupported() -> None:
    profile = _tiff([(0xC001, 0xFFFF, 1, bytes(4))])
    metadata = PngExif.from_chunk(PngExif(profile).to_chunk())
    assert metadata.profile == profile
    with pytest.raises(PngUnsupportedError, match='field type'):
        metadata.validate_profile_structure()


@pytest.mark.parametrize('profile_kind', ['icc', 'exif', 'unsupported_exif'])
def test_document_and_image_writers_reject_bad_profiles_without_writing_or_mutating(
        png_suite_dir: Path, truncated_icc_profile_bytes: bytes, tmp_path: Path, profile_kind: str,
) -> None:
    metadata = (PngIccProfile('Truncated', truncated_icc_profile_bytes) if profile_kind == 'icc' else
                PngExif(_tiff([(0x0112, 3, 1, b'\0\x01\0\0')], following=8)))
    if profile_kind == 'unsupported_exif':
        metadata = PngExif(_tiff([(0xC001, 0xFFFF, 1, bytes(4))]))
    error_type = PngUnsupportedError if profile_kind == 'unsupported_exif' else PngValidationError
    document = PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))
    document.chunks.insert(1, metadata.to_chunk())
    encoded = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    loaded = PngDocument.parse(encoded)
    image = PngImage.from_document(loaded)
    for model in (loaded, image):
        stream = BytesIO(b'existing bytes')
        stream.seek(0, 2)
        with pytest.raises(error_type):
            model.dump(stream)
        assert stream.getvalue() == b'existing bytes'
        assert not stream.closed
        path = tmp_path.joinpath('existing.png')
        path.write_bytes(b'original file')
        with pytest.raises(error_type):
            model.save(path)
        assert path.read_bytes() == b'original file'
    retained, = image.find_metadata(metadata.type)
    assert retained.profile == metadata.profile
    assert loaded.find_chunks(metadata.type)[0].data == metadata.to_chunk().data
    # Removing invalid metadata is an explicit caller action, after inspection.
    image.metadata.remove(retained)
    assert PngImage.parse(image.dump_to_bytes()).bitmap == image.bitmap


def test_wpt_exif_structure_is_valid_and_payload_stays_exact(assets_dir: Path) -> None:
    image = PngImage.load(assets_dir.joinpath('wpt', 'png', 'support', 'exif-orientation-bottom-right.png'))
    metadata, = image.find_metadata(b'eXIf')
    original = metadata.profile
    metadata.validate_profile_structure()
    assert PngImage.parse(image.dump_to_bytes()).find_metadata(b'eXIf')[0].profile == original
