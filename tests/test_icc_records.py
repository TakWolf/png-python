"""ICC named-color and sequence record vectors; PNG assets stay unmodified."""

from io import BytesIO
from pathlib import Path
from struct import pack, unpack_from

import pytest

from png import PngDocument, PngIccProfile, PngImage, PngUnsupportedError, PngValidationError
from png._icc_records import validate_named_colors, validate_profile_sequence


def _name(value: bytes) -> bytes:
    assert len(value) < 32
    return value + bytes(32 - len(value))


def _named(coordinates: int = 3, names: tuple[bytes, ...] = (b'Red', b'Blue')) -> bytes:
    return (b'ncl2' + bytes(4) + pack('>III', 0xA5000000, len(names), coordinates)
            + _name(b'Prefix ') + _name(b' Suffix')
            + b''.join(_name(name) + pack('>3H', 0, 32768, 65535) + bytes(2 * coordinates) for name in names))


def _description(text: bytes = b'', *, unicode_text: bool = False) -> bytes:
    encoded = (text.decode('ascii') + '\0').encode('utf-16-be') if unicode_text else b''
    return (b'desc' + bytes(4) + pack('>I', len(text) + 1) + text + bytes(1)
            + pack('>II', 0, len(encoded) // 2) + encoded + bytes(70))


def _localized(text: str | None = None, *, shared: bool = False) -> bytes:
    if text is None:
        return b'mluc' + bytes(4) + pack('>II', 0, 12)
    encoded = text.encode('utf-16-be')
    count = 2 if shared else 1
    offset = 16 + count * 12
    records = b''.join(language + pack('>II', len(encoded), offset) for language in (b'enUS', b'enGB')[:count])
    return b'mluc' + bytes(4) + pack('>II', count, 12) + records + encoded


def _sequence(records: list[tuple[bytes, bytes]]) -> bytes:
    fixed = b'TEST' + b'MODL' + pack('>Q', 0xA5A5A5A50000000F) + b'CRT '
    return b'pseq' + bytes(4) + pack('>I', len(records)) + b''.join(fixed + maker + model for maker, model in records)


def _u32(data: bytes, offset: int, value: int) -> bytes:
    return data[:offset] + pack('>I', value) + data[offset + 4:]


@pytest.mark.parametrize('coordinates', [0, 1, 3, 15])
@pytest.mark.parametrize('names', [(), (b'',), (b'Red', b'Blue'), (b'Same', b'Same')])
def test_named_color_record_counts_and_optional_coordinates(coordinates: int, names: tuple[bytes, ...]) -> None:
    validate_named_colors(_named(coordinates, names))


def test_named_colors_preserve_flag_bits_special_ascii_and_unused_name_bytes() -> None:
    data = _named(0, (b'Tab\tName', b'Line\nName'))
    data = _u32(data, 8, 0xA5A50003)  # Reserved-for-ICC usage does not specify a zero value.
    data = data[:20] + b'P\0' + b'\xff' * 30 + data[52:]
    validate_named_colors(data)


@pytest.mark.parametrize(('offset', 'damage'), [
    (0, 'header'), (4, 'reserved'), (12, 'count'), (16, 'coordinates'),
    (20, 'terminator'), (52, 'terminator'), (84, 'terminator'),
    (20, 'high_bit'), (52, 'high_bit'), (84, 'high_bit'),
    (0, 'short_record'), (0, 'extra_record'),
])
def test_named_color_bad_sizes_and_name_fields(offset: int, damage: str) -> None:
    data = _named()
    if damage == 'header':
        data = data[:83]
    elif damage == 'reserved':
        data = _u32(data, offset, 1)
    elif damage in ('count', 'coordinates'):
        data = _u32(data, offset, 0xFFFFFFFF)
    elif damage == 'terminator':
        data = data[:offset] + b'A' * 32 + data[offset + 32:]
    elif damage == 'high_bit':
        data = data[:offset] + b'\x80' + data[offset + 1:]
    elif damage == 'short_record':
        data = data[:-1]
    else:
        data += bytes(1)
    with pytest.raises(PngValidationError, match='ICC'):
        validate_named_colors(data)


@pytest.mark.parametrize('records', [
    [], [(_description(), _description())], [(_localized(), _localized())],
    [(_description(b'A'), _localized('B'))], [(_localized('A'), _description(b'B'))],
    [(_localized('A', shared=True), _localized('PNG\U0001f600'))],
    [(_description(b'Maker', unicode_text=True), _description(b'Model', unicode_text=True))],
    [(_description(b'One'), _description(b'Two')), (_localized('Three'), _localized())],
])
def test_profile_sequence_embedded_text_types_and_unaligned_boundaries(records: list[tuple[bytes, bytes]]) -> None:
    # No padding is inserted between descriptions or records, even at odd offsets.
    validate_profile_sequence(_sequence(records))


@pytest.mark.parametrize('damage', ['header', 'reserved', 'count', 'fixed_header', 'missing_model',
                                    'description_reserved', 'ascii_count', 'ascii_terminator',
                                    'unicode_count', 'script_count', 'extra_bytes'])
def test_profile_sequence_legacy_description_bounds(damage: str) -> None:
    data = _sequence([(_description(), _description())])
    if damage == 'header':
        data = data[:11]
    elif damage == 'reserved':
        data = _u32(data, 4, 1)
    elif damage == 'count':
        data = _u32(data, 8, 0xFFFFFFFF)
    elif damage == 'fixed_header':
        # A legal first record followed by an incomplete second fixed header.
        data = _u32(data, 8, 2) + bytes(19)
    elif damage == 'missing_model':
        data = data[:-91]
    elif damage == 'description_reserved':
        data = _u32(data, 36, 1)
    elif damage == 'ascii_count':
        data = _u32(data, 40, 0xFFFFFFFF)
    elif damage == 'ascii_terminator':
        data = data[:44] + b'A' + data[45:]
    elif damage == 'unicode_count':
        data = _u32(data, 49, 0xFFFFFFFF)
    elif damage == 'script_count':
        data = data[:55] + bytes((68,)) + data[56:]
    else:
        data += bytes(4)
    with pytest.raises(PngValidationError, match='ICC'):
        validate_profile_sequence(data)


@pytest.mark.parametrize('damage', ['header', 'count', 'stride', 'string_offset', 'odd_length', 'utf16'])
def test_profile_sequence_multilingual_description_bounds(damage: str) -> None:
    maker = _localized('Maker', shared=True)
    if damage == 'header':
        maker = maker[:12]
    elif damage == 'count':
        maker = _u32(maker, 8, 0xFFFFFFFF)
    elif damage == 'stride':
        maker = _u32(maker, 12, 11)
    elif damage == 'string_offset':
        maker = _u32(maker, 24, 0xFFFFFFFF)
    elif damage == 'odd_length':
        maker = _u32(maker, 20, 3)
    else:
        maker = maker[:-2] + b'\xd8\0'
    data = _sequence([(maker, _localized())])
    with pytest.raises(PngValidationError, match='ICC'):
        validate_profile_sequence(data)


def test_profile_sequence_unknown_description_encoding_is_reported() -> None:
    data = _sequence([(b'zzzz' + bytes(12), _localized())])
    with pytest.raises(PngUnsupportedError, match='embedded description type'):
        validate_profile_sequence(data)


def _with_record(profile: bytes, tag: bytes, payload: bytes) -> bytes:
    count, = unpack_from('>I', profile, 128)
    entries = [unpack_from('>4sII', profile, 132 + 12 * index) for index in range(count)]
    tags = [(kind, profile[offset:offset + size]) for kind, offset, size in entries] + [(tag, payload)]
    table = bytearray()
    body = bytearray()
    for kind, value in tags:
        table.extend(pack('>4sII', kind, 132 + 12 * len(tags) + len(body), len(value)))
        body.extend(value)
        body.extend(bytes(-len(body) % 4))
    header = bytearray(profile[:128])
    header[84:100] = bytes(16)
    result = bytes(header) + pack('>I', len(tags)) + bytes(table) + bytes(body)
    return _u32(result, 0, len(result))


@pytest.mark.parametrize('version', [2, 4])
@pytest.mark.parametrize('tag', [b'ncl2', b'pseq'])
def test_profile_record_tags_pass_complete_profile_checks(assets_dir: Path, version: int, tag: bytes) -> None:
    profile = assets_dir.joinpath('icc', 'sRGB2014.icc' if version == 2 else 'sRGB_v4_ICC_preference.icc').read_bytes()
    text = _description(b'Model') if version == 2 else _localized('Model')
    payload = _named() if tag == b'ncl2' else _sequence([(text, text)])
    PngIccProfile('Record layout vector', _with_record(profile, tag, payload)).validate_profile_tags()


@pytest.mark.parametrize('representation', ['image', 'document'])
@pytest.mark.parametrize('tag', [b'ncl2', b'pseq'])
@pytest.mark.parametrize('damaged', [False, True])
def test_icc_record_roundtrip_and_write_protection(
        icc_profile_bytes: bytes, png_suite_dir: Path, tmp_path: Path,
        representation: str, tag: bytes, damaged: bool,
) -> None:
    payload = _named() if tag == b'ncl2' else _sequence([(_description(), _localized('Model'))])
    if damaged:
        payload = _u32(payload, 12 if tag == b'ncl2' else 8, 0xFFFFFFFF)
    profile = _with_record(icc_profile_bytes, tag, payload)
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.metadata.append(PngIccProfile('Record layout vector', profile))
    document = image.to_document()
    raw = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    restored = PngImage.parse(raw)
    assert restored.find_metadata(b'iCCP')[0].profile == profile
    result = restored if representation == 'image' else PngDocument.parse(raw)
    if not damaged:
        written = PngImage.parse(result.dump_to_bytes())
        assert written.bitmap == image.bitmap
        assert written.find_metadata(b'iCCP')[0].profile == profile
        return
    stream = BytesIO(b'unchanged')
    with pytest.raises(PngValidationError, match='ICC'):
        result.dump(stream)
    assert stream.getvalue() == b'unchanged'
    target = tmp_path.joinpath('existing.png')
    target.write_bytes(b'unchanged')
    with pytest.raises(PngValidationError, match='ICC'):
        result.save(target)
    assert target.read_bytes() == b'unchanged'
