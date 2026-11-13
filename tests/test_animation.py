from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
from struct import pack, unpack

import pytest

from png import (
    PngAnimation, PngBlendOp, PngChunk, PngColorType, PngDisposeOp, PngDocument,
    PngFilterType, PngFrame, PngFrameControl, PngHeader, PngImage,
    PngInterlaceMethod, PngParseError, PngValidationError,
)

_WPT_ROOT = Path(__file__).parents[1].joinpath('assets', 'wpt')
_APNG_ROOT = _WPT_ROOT.joinpath('png', 'apng')
_ANIMATED = sorted(path.name for path in _APNG_ROOT.joinpath('support').glob('[0-9]*.png'))
_VISUAL = sorted(path.name for path in _APNG_ROOT.glob('*.html')
                 if 'rel="match"' in path.read_text() and path.name != 'fDAT-inherits-cICP.html')
_BASIC = sorted(path.name for path in Path(__file__).parents[1].joinpath('assets', 'png-suite').glob('basn*.png'))


def test_wpt_provenance() -> None:
    manifest = json.loads(_WPT_ROOT.joinpath('SOURCE.json').read_text())
    assert manifest['commit'] == '44d24bce619f53d07b311f2732f2c50adc407399'
    assert len(manifest['files']) == 84
    assert len(_ANIMATED) == 35
    assert len(_VISUAL) == 28
    for entry in manifest['files']:
        data = _WPT_ROOT.joinpath(entry['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry['sha256']
        assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == entry['git_blob']


@pytest.mark.parametrize('name', _ANIMATED)
def test_wpt_animation_roundtrip(name: str) -> None:
    original = PngImage.load(_APNG_ROOT.joinpath('support', name))
    assert original.animation is not None
    restored = PngImage.parse(original.dump_to_bytes(idat_chunk_size=17))
    assert restored.bitmap == original.bitmap
    assert restored.palette == original.palette
    assert restored.palette_alpha == original.palette_alpha
    assert restored.animation.num_plays == original.animation.num_plays
    assert restored.animation.num_frames == original.animation.num_frames
    default = original.animation.default_image_control
    actual_default = restored.animation.default_image_control
    assert (default is None) == (actual_default is None)
    if default is not None:
        assert default.to_chunk(0).data == actual_default.to_chunk(0).data
    for source, actual in zip(original.animation.frames, restored.animation.frames):
        assert source.bitmap == actual.bitmap
        assert source.control.to_chunk(0).data == actual.control.to_chunk(0).data


def _visible_rgba8(image: PngImage) -> list[list[int]]:
    maximum = (1 << image.header.bit_depth) - 1
    result = []
    for row in image.bitmap:
        target = []
        for index in range(0, len(row), 4):
            pixel = [(value * 255 + maximum // 2) // maximum for value in row[index:index + 4]]
            if pixel[3] == 0:
                pixel[:3] = [0, 0, 0]  # Invisible RGB values are not a visual difference.
            target.extend(pixel)
        result.append(target)
    return result


@pytest.mark.parametrize('name', _VISUAL)
def test_wpt_final_state_matches_official_reference(name: str) -> None:
    html = _APNG_ROOT.joinpath(name).read_text()
    source, = re.findall(r'src="(support/[^"]+\.png)"', html)
    reference, = re.findall(r'rel="match" href="([^"]+)"', html)
    image = PngImage.load(_APNG_ROOT.joinpath(source))
    last = None
    for frame in image.render_frames():
        last = frame.image
    expected_files = re.findall(r'src="(support/[^"]+\.png)"', _APNG_ROOT.joinpath(reference).read_text())
    if expected_files:
        expected = next(PngImage.load(_APNG_ROOT.joinpath(expected_files[0])).render_frames()).image
        assert _visible_rgba8(last) == _visible_rgba8(expected)
    else:
        # The checkerboard reference has no foreground image at all.
        assert all(row[index] == 0 for row in last.bitmap for index in range(3, len(row), 4))


def test_color_metadata_inherited_by_rendered_frame() -> None:
    image = PngImage.load(_APNG_ROOT.joinpath('support', '062.png'))
    expected = [chunk.data for chunk in image.ancillary_chunks if chunk.type == b'cICP']
    assert len(expected) == 1
    for rendered in image.render_frames():
        assert [chunk.data for chunk in rendered.image.ancillary_chunks if chunk.type == b'cICP'] == expected


@pytest.mark.parametrize('name', _BASIC)
@pytest.mark.parametrize('interlace', list(PngInterlaceMethod))
@pytest.mark.parametrize('poster', [True, False])
def test_animation_encoding_all_sample_formats(png_suite_dir: Path, name: str, interlace, poster: bool) -> None:
    image = PngImage.load(png_suite_dir.joinpath(name))
    image.header.dimensions = (2, 1)
    image.header.interlace_method = interlace
    channels = image.header.channels
    image.bitmap = [image.bitmap[0][:2 * channels]]
    image.animation = PngAnimation(
        frames=[PngFrame(PngFrameControl((1, 1), offset=(1, 0), delay_num=3, delay_den=0),
                         [image.bitmap[0][channels:]])],
        default_image_control=None if poster else PngFrameControl((2, 1), delay_num=1, delay_den=60),
        num_plays=2,
    )
    restored = PngImage.parse(image.dump_to_bytes(filter_type=PngFilterType.PAETH, idat_chunk_size=1))
    assert restored.animation.num_frames == (1 if poster else 2)
    assert restored.animation.frames[0].bitmap == image.animation.frames[0].bitmap
    assert restored.animation.frames[0].control.delay_den == 0
    assert restored.animation.frames[0].control.delay == Fraction(3, 100)
    assert [frame.image.bitmap for frame in restored.render_frames()] == [frame.image.bitmap for frame in image.render_frames()]


def _animation_image(default: bool = True) -> PngImage:
    return PngImage(PngHeader((2, 1)), [[255, 0, 0, 255, 255, 0, 0, 255]], animation=PngAnimation(
        default_image_control=PngFrameControl((2, 1)) if default else None,
        frames=[PngFrame(PngFrameControl((1, 1), offset=(1, 0)), [[0, 255, 0, 128]])],
    ))


def test_poster_does_not_seed_animation_canvas() -> None:
    frames = list(_animation_image(default=False).render_frames())
    assert len(frames) == 1
    assert frames[0].image.bitmap == [[0, 0, 0, 0, 0, 255, 0, 128]]


def test_over_is_straight_alpha_and_source_replaces_transparent_pixels() -> None:
    image = _animation_image()
    image.animation.frames[0].control.blend_op = PngBlendOp.OVER
    frames = list(image.render_frames())
    assert frames[-1].image.bitmap[0][4:] == [127, 128, 0, 255]
    image.animation.frames[0].control.blend_op = PngBlendOp.SOURCE
    image.animation.frames[0].bitmap = [[1, 2, 3, 0]]
    assert list(image.render_frames())[-1].image.bitmap[0][4:] == [1, 2, 3, 0]


def test_snapshots_are_independent_and_rendering_restarts() -> None:
    image = _animation_image()
    original = deepcopy(image.bitmap)
    iterator = image.render_frames()
    first = next(iterator)
    first.image.bitmap[0][0] = 0
    second = next(iterator)
    assert second.image.bitmap[0][:4] == [255, 0, 0, 255]
    assert image.bitmap == original
    assert next(image.render_frames()).image.bitmap == original


def test_16_bit_composition_retains_low_bits() -> None:
    image = PngImage(PngHeader((1, 1), bit_depth=16), [[0x1234, 0x2345, 0x3456, 0xFFFF]],
                     animation=PngAnimation(default_image_control=PngFrameControl((1, 1))))
    rendered = next(image.render_frames())
    assert rendered.image.header.bit_depth == 16
    assert rendered.image.bitmap == image.bitmap
    assert rendered.delay == Fraction(1, 10)


@pytest.mark.parametrize(('depth', 'half', 'expected'), [
    (8, 128, [85, 0, 170, 192]),
    (16, 32768, [21845, 0, 43690, 49152]),
])
def test_over_with_translucent_destination(depth: int, half: int, expected: list[int]) -> None:
    maximum = (1 << depth) - 1
    image = PngImage(PngHeader((1, 1), bit_depth=depth), [[maximum, 0, 0, half]],
                     animation=PngAnimation(
                         default_image_control=PngFrameControl((1, 1)),
                         frames=[PngFrame(PngFrameControl((1, 1), blend_op=PngBlendOp.OVER),
                                          [[0, 0, maximum, half]])],
                     ))
    assert list(image.render_frames())[-1].image.bitmap == [expected]


def test_raw_apng_rechunking_preserves_animation() -> None:
    source = _animation_image().dump_to_bytes()
    document = PngDocument.parse(source)
    index = next(index for index, chunk in enumerate(document.chunks) if chunk.type == b'IDAT')
    original = document.chunks[index].data
    document.chunks[index:index + 1] = [PngChunk(b'IDAT', original[:1]), PngChunk(b'IDAT', original[1:])]
    restored = PngImage.parse(document.dump_to_bytes())
    assert restored.animation.num_frames == 2
    assert restored.bitmap == _animation_image().bitmap


def test_animation_sequence_and_empty_data_parts() -> None:
    image = PngImage.load(_APNG_ROOT.joinpath('support', '006.png'))
    assert image.animation.num_frames == 1
    document = _animation_image().to_document(idat_chunk_size=1)
    sequence = [unpack('>I', chunk.data[:4])[0] for chunk in document.chunks if chunk.type in (b'fcTL', b'fdAT')]
    assert sequence == list(range(len(sequence)))


@pytest.mark.parametrize('damage', ['no_actl', 'zero_frames', 'count', 'plays', 'gap', 'duplicate', 'missing_data', 'fdAT_before_control', 'default_size', 'bounds', 'bad_disposal', 'bad_blend'])
def test_invalid_animation_envelopes(damage: str) -> None:
    document = _animation_image().to_document()
    controls = document.find_chunks(b'fcTL')
    actl = document.find_chunks(b'acTL')[0]
    fdat = document.find_chunks(b'fdAT')[0]
    if damage == 'no_actl':
        document.chunks.remove(actl)
    elif damage == 'zero_frames':
        actl.data = pack('>II', 0, 0)
    elif damage == 'count':
        actl.data = pack('>II', 99, 0)
    elif damage == 'plays':
        actl.data = pack('>II', 2, 0x80000000)
    elif damage in ('gap', 'duplicate'):
        fdat.data = pack('>I', 10 if damage == 'gap' else 1) + fdat.data[4:]
    elif damage == 'missing_data':
        document.chunks.remove(fdat)
    elif damage == 'fdAT_before_control':
        document.chunks.remove(controls[1])
        fdat.data = pack('>I', 1) + fdat.data[4:]
    else:
        index = 0 if damage == 'default_size' else 1
        control = PngFrameControl.from_chunk(controls[index])
        if damage == 'default_size':
            control.width = 1
        elif damage == 'bounds':
            control.offset_x = 2
        elif damage == 'bad_disposal':
            controls[index].data = controls[index].data[:-2] + b'\x03' + controls[index].data[-1:]
        else:
            controls[index].data = controls[index].data[:-1] + b'\x02'
        if damage in ('default_size', 'bounds'):
            controls[index].data = control.to_chunk(index).data
    encoded = b'\x89PNG\r\n\x1a\n' + b''.join(chunk.dump_to_bytes() for chunk in document.chunks)
    with pytest.raises(PngValidationError):
        document.validate()
    with pytest.raises(PngParseError):
        PngImage.parse(encoded)


def test_bad_frame_zlib_is_not_accepted_as_a_good_animation() -> None:
    document = _animation_image().to_document()
    frame = document.find_chunks(b'fdAT')[0]
    frame.data = frame.data[:4] + b'bad compressed data'
    with pytest.raises(PngParseError, match='zlib'):
        PngImage.from_document(document)


def test_frame_control_payload_conversion() -> None:
    control = PngFrameControl((2, 3), (4, 5), 65535, 0, PngDisposeOp.PREVIOUS, PngBlendOp.OVER)
    chunk = control.to_chunk(7)
    assert chunk.length == 26
    assert unpack('>I', chunk.data[:4]) == (7,)
    assert PngFrameControl.from_chunk(chunk).to_chunk(7).data == chunk.data
