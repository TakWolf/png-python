import zlib
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest

from png import (
    PngCompressedText,
    PngCompressionStrategy,
    PngDocument,
    PngFilterType,
    PngIccProfile,
    PngImage,
    PngInternationalText,
    PngValidationError,
)

_SAMPLES = ['basn0g01.png', 'basn3p04.png', 'basi0g16.png', 'basi2c08.png', 'basn4a08.png', 'basn6a16.png']


def _streams(document: PngDocument) -> list[bytes]:
    """Collect the default zlib stream and each separate APNG frame stream."""
    streams = [bytearray()]
    seen_data = False
    for chunk in document.chunks:
        if chunk.type == b'IDAT':
            streams[0].extend(chunk.data)
            seen_data = True
        elif chunk.type == b'fcTL' and seen_data:
            streams.append(bytearray())
        elif chunk.type == b'fdAT':
            streams[-1].extend(chunk.data[4:])
    return [bytes(data) for data in streams]


@pytest.mark.parametrize('strategy', list(PngCompressionStrategy))
@pytest.mark.parametrize('name', _SAMPLES)
def test_official_samples_use_requested_strategy(png_suite_dir: Path, name: str, strategy) -> None:
    image = PngImage.load(png_suite_dir.joinpath(name))
    # zlib-ng may encode the same bytes differently when fed scanlines rather
    # than one buffer. Check strategy forwarding and decompressed data instead.
    default = image.to_document(filter_type=PngFilterType.NONE)
    (raw,) = [zlib.decompress(data) for data in _streams(default)]
    options = {'filter_type': PngFilterType.NONE, 'compression_strategy': strategy, 'idat_chunk_size': 7}
    with patch('png._pixels.zlib.compressobj', wraps=zlib.compressobj) as compressobj:
        document = image.to_document(**options)
    assert [call.kwargs['strategy'] for call in compressobj.call_args_list] == [strategy]
    assert [zlib.decompress(data) for data in _streams(document)] == [raw]
    if strategy == PngCompressionStrategy.DEFAULT:
        assert document.dump_to_bytes() == image.dump_to_bytes(filter_type=PngFilterType.NONE, idat_chunk_size=7)
    restored = PngImage.from_document(document)
    assert restored.header.to_chunk().data == image.header.to_chunk().data
    assert restored.bitmap == image.bitmap
    assert restored.palette == image.palette
    assert restored.palette_alpha == image.palette_alpha
    assert restored.transparent_color == image.transparent_color


@pytest.mark.parametrize('strategy', list(PngCompressionStrategy))
@pytest.mark.parametrize('name', ['007.png', '062.png'])
def test_strategy_reaches_every_apng_frame(apng_dir: Path, name: str, strategy) -> None:
    image = PngImage.load(apng_dir.joinpath('support', name))
    default = image.to_document(filter_type=PngFilterType.NONE)
    raw = [zlib.decompress(data) for data in _streams(default)]
    with patch('png._pixels.zlib.compressobj', wraps=zlib.compressobj) as compressobj:
        document = image.to_document(filter_type=PngFilterType.NONE, compression_strategy=strategy, idat_chunk_size=17)
    assert len(raw) == 1 + len(image.animation.frames)
    assert [call.kwargs['strategy'] for call in compressobj.call_args_list] == [strategy] * len(raw)
    assert [zlib.decompress(data) for data in _streams(document)] == raw
    if strategy == PngCompressionStrategy.DEFAULT:
        assert document.dump_to_bytes() == image.dump_to_bytes(filter_type=PngFilterType.NONE, idat_chunk_size=17)
    restored = PngImage.from_document(document)
    assert restored.bitmap == image.bitmap
    assert restored.animation.num_plays == image.animation.num_plays
    assert restored.animation.num_frames == image.animation.num_frames
    for original, actual in zip(image.animation.frames, restored.animation.frames, strict=True):
        assert original.bitmap == actual.bitmap
        assert original.control.to_chunk(0).data == actual.control.to_chunk(0).data


def test_strategy_is_available_on_all_output_apis(png_suite_dir: Path, tmp_path: Path) -> None:
    image = PngImage.load(png_suite_dir.joinpath('basn6a08.png'))
    options = {'compression_strategy': PngCompressionStrategy.RLE, 'compression_level': 1}
    expected = image.to_document(**options).dump_to_bytes()
    assert image.dump_to_bytes(**options) == expected
    stream = BytesIO()
    image.dump(stream, **options)
    assert stream.getvalue() == expected
    destination = tmp_path.joinpath('rle.png')
    image.save(destination, **options)
    assert destination.read_bytes() == expected


@pytest.mark.parametrize('invalid', [-1, 5, True, False, 1.0, 'RLE', None, 1 << 64])
def test_invalid_strategy_preserves_output(png_suite_dir: Path, tmp_path: Path, invalid) -> None:
    image = PngImage.load(png_suite_dir.joinpath('basn0g01.png'))
    stream = BytesIO(b'keep stream')
    stream.seek(3)
    with pytest.raises(PngValidationError, match='compression strategy'):
        image.dump(stream, compression_strategy=invalid)
    assert stream.getvalue() == b'keep stream'
    assert stream.tell() == 3
    destination = tmp_path.joinpath('preserved.png')
    destination.write_bytes(b'keep file')
    with pytest.raises(PngValidationError, match='compression strategy'):
        image.save(destination, compression_strategy=invalid)
    assert destination.read_bytes() == b'keep file'
    missing = tmp_path.joinpath('not-created.png')
    with pytest.raises(PngValidationError, match='compression strategy'):
        image.save(missing, compression_strategy=invalid)
    assert not missing.exists()


def test_strategy_keeps_metadata_compression(png_suite_dir: Path, icc_profile_bytes: bytes) -> None:
    image = PngImage.load(png_suite_dir.joinpath('basn6a08.png'))
    image.metadata.extend(
        [
            PngCompressedText('Comment', 'Repeated text ' * 20),
            PngInternationalText('Description', 'Repeated Unicode text ' * 20, compressed=True),
            PngIccProfile('RGB profile', icc_profile_bytes),
        ]
    )
    default = image.to_document()
    rle = image.to_document(compression_strategy=PngCompressionStrategy.RLE)
    for kind in (b'zTXt', b'iTXt', b'iCCP'):
        assert default.find_chunks(kind)[0].data == rle.find_chunks(kind)[0].data
