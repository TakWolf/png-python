import zlib
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from struct import pack

import pytest

from png import (
    PngAnimation,
    PngChunk,
    PngCompressedText,
    PngCrcError,
    PngDocument,
    PngFrame,
    PngFrameControl,
    PngIccProfile,
    PngImage,
    PngInternationalText,
    PngLimitError,
    PngParseError,
    PngReadLimits,
    PngText,
    PngValidationError,
)

_LIMITS = (
    'max_chunk_bytes',
    'max_total_bytes',
    'max_chunks',
    'max_pixels',
    'max_total_pixels',
    'max_frames',
    'max_metadata_bytes',
)


def _document(png_suite_dir: Path) -> PngDocument:
    return PngDocument.load(png_suite_dir.joinpath('basn2c08.png'))


def _with_metadata(png_suite_dir: Path, chunks: list[PngChunk]) -> PngDocument:
    source = _document(png_suite_dir)
    return PngDocument([source.chunks[0], *chunks, *source.find_chunks(b'IDAT'), source.chunks[-1]])


def _assert_limit(call, name: str, maximum: int, actual: int | None = None) -> PngLimitError:
    with pytest.raises(PngLimitError) as caught:
        call()
    error = caught.value
    assert isinstance(error, PngParseError)
    assert error.limit == name
    assert error.maximum == maximum
    assert error.actual > maximum
    if actual is not None:
        assert error.actual == actual
    return error


@pytest.mark.parametrize('name', _LIMITS)
@pytest.mark.parametrize('value', [-1, True, 1.5, '2'])
def test_invalid_policy_is_a_configuration_error_before_reading(name: str, value) -> None:
    policy = PngReadLimits(**{name: value})
    for parse in (PngChunk.parse, PngDocument.parse, PngImage.parse):
        stream = BytesIO(b'unread')
        with pytest.raises(PngValidationError):
            parse(stream, limits=policy)
        assert stream.tell() == 0
    with pytest.raises(PngValidationError):
        policy.validate()


@pytest.mark.parametrize('parse', [PngChunk.parse, PngDocument.parse, PngImage.parse])
def test_invalid_policy_type(parse) -> None:
    with pytest.raises(PngValidationError, match='PngReadLimits'):
        parse(b'', limits={})


@pytest.mark.parametrize('name', _LIMITS)
def test_policy_accepts_zero_and_unbounded_values(name: str) -> None:
    policy = PngReadLimits(**{name: 0})
    policy.validate()
    setattr(policy, name, None)
    policy.validate()


def test_chunk_payload_limit_is_checked_before_reading_or_allocation() -> None:
    # No huge payload is allocated: the legal advertised size alone triggers policy.
    stream = BytesIO(pack('>I4s', 0x7FFFFFFF, b'IDAT') + b'not consumed')
    _assert_limit(
        lambda: PngChunk.parse(stream, limits=PngReadLimits(max_chunk_bytes=1024)), 'max_chunk_bytes', 1024, 0x7FFFFFFF
    )
    assert stream.tell() == 8
    assert stream.read() == b'not consumed'
    assert not stream.closed


def test_chunk_size_is_payload_but_total_size_includes_envelope() -> None:
    encoded = bytes.fromhex('00000000 49454e44 ae426082')
    chunk = PngChunk.parse(encoded, limits=PngReadLimits(max_chunk_bytes=0, max_total_bytes=12, max_chunks=1))
    assert chunk.type == b'IEND'
    stream = BytesIO(encoded)
    _assert_limit(lambda: PngChunk.parse(stream, limits=PngReadLimits(max_total_bytes=11)), 'max_total_bytes', 11, 12)
    assert stream.tell() == 0


def test_png_total_size_includes_signature_but_not_external_stream_data(png_suite_dir: Path) -> None:
    encoded = png_suite_dir.joinpath('basn2c08.png').read_bytes()
    policy = PngReadLimits(max_total_bytes=len(encoded))
    stream = BytesIO(b'prefix' + encoded + b'suffix')
    stream.seek(6)
    assert PngDocument.parse(stream, limits=policy).dump_to_bytes() == encoded
    assert stream.read() == b'suffix'
    assert not stream.closed
    policy.max_total_bytes -= 1
    _assert_limit(lambda: PngImage.parse(encoded, limits=policy), 'max_total_bytes', len(encoded) - 1)


def test_document_chunk_limit_rejects_payload_and_counts_empty_chunks(png_suite_dir: Path) -> None:
    document = _document(png_suite_dir)
    document.chunks.insert(-1, PngChunk(b'vpAg', b'payload'))
    data = document.dump_to_bytes()
    index = len(document.chunks) - 2
    offset = 8 + sum(chunk.length + 12 for chunk in document.chunks[:index])
    stream = BytesIO(data)
    _assert_limit(
        lambda: PngDocument.parse(stream, limits=PngReadLimits(max_chunks=index)), 'max_chunks', index, index + 1
    )
    assert stream.tell() == offset
    document.chunks[-2].data = b''
    _assert_limit(
        lambda: PngDocument.parse(document.dump_to_bytes(), limits=PngReadLimits(max_chunks=index)),
        'max_chunks',
        index,
        index + 1,
    )


def test_document_chunk_bytes_do_not_reset_at_each_chunk(png_suite_dir: Path) -> None:
    document = _document(png_suite_dir)
    document.chunks.insert(-1, PngChunk(b'vpAg', bytes(40)))
    data = document.dump_to_bytes()
    maximum = len(data) - 13
    stream = BytesIO(data)
    _assert_limit(
        lambda: PngDocument.parse(stream, limits=PngReadLimits(max_total_bytes=maximum)), 'max_total_bytes', maximum
    )
    assert stream.tell() < len(data) - 12


def test_pixel_limit_is_checked_after_ihdr_before_reading_idat(png_suite_dir: Path) -> None:
    document = _document(png_suite_dir)
    stream = BytesIO(document.dump_to_bytes())
    _assert_limit(lambda: PngImage.parse(stream, limits=PngReadLimits(max_pixels=1023)), 'max_pixels', 1023, 1024)
    assert stream.tell() == 33


def test_from_document_checks_policy_before_decoding_pixels(png_suite_dir: Path, monkeypatch) -> None:
    document = _document(png_suite_dir)

    def unexpected_decode(*args, **kwargs):
        pytest.fail('pixel decoder must not run after an input policy was exceeded')

    monkeypatch.setattr('png.image.decode_pixels', unexpected_decode)
    for name, maximum in [
        ('max_pixels', 1023),
        ('max_total_pixels', 1023),
        ('max_chunk_bytes', 12),
        ('max_total_bytes', 32),
        ('max_chunks', 0),
    ]:
        _assert_limit(
            lambda name=name, maximum=maximum: PngImage.from_document(
                document, limits=PngReadLimits(**{name: maximum})
            ),
            name,
            maximum,
        )


@pytest.mark.parametrize('default_in_animation', [False, True])
def test_apng_counts_poster_once_and_uses_local_frame_rectangles(
    png_suite_dir: Path,
    default_in_animation: bool,
) -> None:
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.animation = PngAnimation(
        default_image_control=PngFrameControl(image.dimensions) if default_in_animation else None,
        frames=[
            PngFrame(PngFrameControl((1, 1)), [[1, 2, 3]]),
            PngFrame(PngFrameControl((2, 1)), [[1, 2, 3, 4, 5, 6]]),
        ],
    )
    document = image.to_document()
    policy = PngReadLimits(max_pixels=1024, max_total_pixels=1027, max_frames=2 + default_in_animation)
    restored = PngImage.parse(document.dump_to_bytes(), limits=policy)
    assert [frame.control.dimensions for frame in restored.animation.frames] == [(1, 1), (2, 1)]
    policy.max_total_pixels = 1026
    _assert_limit(lambda: PngImage.from_document(document, limits=policy), 'max_total_pixels', 1026, 1027)


def test_declared_animation_limit_is_checked_before_reading_frames(png_suite_dir: Path) -> None:
    document = _document(png_suite_dir)
    document.chunks.insert(1, PngChunk(b'acTL', pack('>II', 100000, 0)))
    # Assemble the intentionally incomplete animation without document validation.
    data = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    stream = BytesIO(data)
    _assert_limit(lambda: PngDocument.parse(stream, limits=PngReadLimits(max_frames=2)), 'max_frames', 2, 100000)
    assert stream.tell() == 33 + 20


def test_actual_animation_frames_cannot_bypass_declared_limit(png_suite_dir: Path) -> None:
    image = PngImage.load(png_suite_dir.joinpath('basn2c08.png'))
    image.animation = PngAnimation(frames=[PngFrame(PngFrameControl((1, 1)), [[1, 2, 3]]) for _ in range(3)])
    document = image.to_document()
    document.find_chunks(b'acTL')[0].data = pack('>II', 1, 0)
    data = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    _assert_limit(lambda: PngImage.parse(data, limits=PngReadLimits(max_frames=2)), 'max_frames', 2, 3)


@pytest.mark.parametrize(
    ('item', 'decoded_size'),
    [
        (PngText('K', 'abc'), 5),
        (PngCompressedText('K', 'abc'), 6),
        ('icc_profile', 3027),
        (PngInternationalText('K', '中文', 'zh', '说明', compressed=False), 20),
        (PngInternationalText('K', '中文', 'zh', '说明', compressed=True), 20),
        (PngChunk(b'vpAg', b'unknown'), 7),
    ],
)
def test_metadata_size_includes_headers_and_expanded_encoded_bytes(
    png_suite_dir: Path,
    icc_profile_bytes: bytes,
    item,
    decoded_size: int,
) -> None:
    if item == 'icc_profile':
        item = PngIccProfile('K', icc_profile_bytes)
    chunk = item if isinstance(item, PngChunk) else item.to_chunk()
    document = _with_metadata(png_suite_dir, [chunk])
    data = document.dump_to_bytes()
    PngImage.parse(data, limits=PngReadLimits(max_metadata_bytes=decoded_size))
    _assert_limit(
        lambda: PngDocument.parse(data, limits=PngReadLimits(max_metadata_bytes=decoded_size - 1)),
        'max_metadata_bytes',
        decoded_size - 1,
        decoded_size,
    )


def test_metadata_budget_accumulates_across_compressed_and_raw_chunks(png_suite_dir: Path) -> None:
    document = _with_metadata(
        png_suite_dir,
        [PngText('K', 'abc').to_chunk(), PngCompressedText('K', 'abc').to_chunk(), PngChunk(b'vpAg', b'opaque')],
    )
    policy = PngReadLimits(max_metadata_bytes=17)
    PngImage.from_document(document, limits=policy)
    policy.max_metadata_bytes = 16
    _assert_limit(lambda: PngImage.from_document(document, limits=policy), 'max_metadata_bytes', 16, 17)


@pytest.mark.parametrize('kind', [b'zTXt', b'iTXt', b'iCCP'])
def test_metadata_expansion_stops_with_one_byte_lookahead(
    png_suite_dir: Path,
    monkeypatch,
    kind: bytes,
) -> None:
    prefix = {b'zTXt': b'K\0\0', b'iTXt': b'K\0\x01\0\0\0', b'iCCP': b'K\0\0'}[kind]
    expanded = bytearray(b'A' * (2 * 1024 * 1024))
    if kind == b'iCCP':
        expanded[16:20] = b'RGB '
        expanded[36:40] = b'acsp'
    document = _with_metadata(png_suite_dir, [PngChunk(kind, prefix + zlib.compress(expanded))])
    # Serialize raw envelopes: normal dumping would first decompress metadata for validation.
    data = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    actual_decompressobj = zlib.decompressobj
    produced = []

    class GuardedInflater:
        def __init__(self):
            self.inner = actual_decompressobj()

        def decompress(self, block, max_length=0):
            assert 0 < max_length <= 1025
            result = self.inner.decompress(block, max_length)
            produced.append(len(result))
            return result

        def __getattr__(self, name):
            return getattr(self.inner, name)

    monkeypatch.setattr('png.metadata.zlib.decompressobj', GuardedInflater)
    _assert_limit(
        lambda: PngImage.parse(data, limits=PngReadLimits(max_metadata_bytes=1024)), 'max_metadata_bytes', 1024, 1025
    )
    assert sum(produced) == 1025 - len(prefix)


def test_policy_counters_are_per_operation_and_not_stored_on_models(png_suite_dir: Path, tmp_path: Path) -> None:
    document = _with_metadata(png_suite_dir, [PngCompressedText('K', 'abc').to_chunk()])
    data = document.dump_to_bytes()
    policy = PngReadLimits(
        max_total_bytes=len(data),
        max_chunks=len(document.chunks),
        max_pixels=1024,
        max_total_pixels=1024,
        max_frames=0,
        max_metadata_bytes=6,
    )
    before = deepcopy(vars(policy))
    for _ in range(2):
        loaded = PngDocument.parse(data, limits=policy)
        loaded.validate(limits=policy)
        image = PngImage.from_document(loaded, limits=policy)
        assert image.bitmap == PngImage.parse(data, limits=policy).bitmap
    assert vars(policy) == before
    destination = tmp_path.joinpath('official-with-text.png')
    document.save(destination)
    PngDocument.load(destination, limits=policy)
    PngImage.load(destination, limits=policy)
    policy.max_pixels = 0
    _assert_limit(lambda: PngImage.load(destination, limits=policy), 'max_pixels', 0, 1024)
    image.validate()  # The earlier read policy is not attached to the image.


def test_crc_and_format_errors_keep_their_types_with_limits(png_suite_dir: Path) -> None:
    document = _document(png_suite_dir)
    data = document.dump_to_bytes()
    with pytest.raises(PngCrcError):
        PngImage.parse(data[:-1] + bytes([data[-1] ^ 1]), limits=PngReadLimits())
    with pytest.raises(PngParseError) as caught:
        PngImage.parse(data[:-1], limits=PngReadLimits())
    assert not isinstance(caught.value, PngLimitError)


def test_unrestricted_policy_preserves_pngsuite_and_wpt_behavior(png_suite_dir: Path, assets_dir: Path) -> None:
    policy = PngReadLimits()
    for path in [
        png_suite_dir.joinpath('basn0g01.png'),
        png_suite_dir.joinpath('basn6a16.png'),
        png_suite_dir.joinpath('basn3p08.png'),
        assets_dir.joinpath('wpt', 'png', 'apng', 'support', '001.png'),
    ]:
        original = PngImage.load(path)
        bounded = PngImage.load(path, limits=policy)
        assert bounded.bitmap == original.bitmap
        assert bounded.dump_to_bytes() == original.dump_to_bytes()
