"""Animation envelope rules; compressed pixel streams are decoded separately."""

from copy import copy
from struct import unpack

from png._validation import check_integer
from png.animation import PngFrameControl
from png.chunk import PngChunk
from png.error import PngValidationError
from png.header import PngHeader


def frame_header(header: PngHeader, dimensions: tuple[int, int]) -> PngHeader:
    result = copy(header)
    result.dimensions = dimensions
    return result


def scan_animation(
        chunks: list[PngChunk], header: PngHeader,
) -> tuple[int, list[tuple[PngFrameControl, list[PngChunk], bool]]] | None:
    controls = [chunk for chunk in chunks if chunk.type == b'acTL']
    if not controls:
        if any(chunk.type in (b'fcTL', b'fdAT') for chunk in chunks):
            raise PngValidationError('animation chunks require acTL')
        return None
    if len(controls) != 1 or controls[0].length != 8:
        raise PngValidationError('exactly one eight-byte acTL is required')
    declared, plays = unpack('>II', controls[0].data)
    check_integer('number of frames', declared, 1, 0x7FFFFFFF)
    check_integer('number of plays', plays, 0, 0x7FFFFFFF)
    frames: list[tuple[PngFrameControl, list[PngChunk], bool]] = []
    sequence = 0
    seen_data = False
    for chunk in chunks:
        if chunk.type == b'acTL' and seen_data:
            raise PngValidationError('acTL must precede IDAT')
        if chunk.type in (b'fcTL', b'fdAT'):
            actual, = unpack('>I', chunk.data[:4])
            check_integer('sequence number', actual, 0, 0x7FFFFFFF)
            if actual != sequence:
                raise PngValidationError(f'expected APNG sequence number {sequence}, got {actual}')
            sequence += 1
        if chunk.type == b'fcTL':
            if frames and not frames[-1][1]:
                raise PngValidationError('animation frame has no image data')
            control = PngFrameControl.from_chunk(chunk)
            control.validate(header.dimensions)
            is_default = not seen_data
            if is_default and (control.dimensions != header.dimensions or control.offset != (0, 0)):
                raise PngValidationError('the default frame must cover the entire canvas at offset (0, 0)')
            frames.append((control, [], is_default))
        elif chunk.type == b'IDAT':
            seen_data = True
            if frames:
                if not frames[-1][2]:
                    raise PngValidationError('IDAT may only supply the default frame')
                frames[-1][1].append(chunk)
        elif chunk.type == b'fdAT':
            if not seen_data or not frames or frames[-1][2]:
                raise PngValidationError('fdAT requires a non-default frame control after IDAT')
            frames[-1][1].append(chunk)
    if len(frames) != declared:
        raise PngValidationError(f'acTL declares {declared} frames, found {len(frames)}')
    if not frames[-1][1]:
        raise PngValidationError('animation frame has no image data')
    return plays, frames
