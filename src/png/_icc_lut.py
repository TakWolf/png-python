"""ICC.1 LUT storage checks; these do not evaluate color transforms."""

from math import prod
from struct import unpack_from

from png.error import PngValidationError


LUT_TYPES = frozenset((b'mft1', b'mft2', b'mAB ', b'mBA '))
_IDENTITY = (65536, 0, 0, 0, 65536, 0, 0, 0, 65536)


def curve_end(data: bytes, offset: int = 0) -> int:
    """Return the unpadded end of a complete embedded curve, without copying it."""
    if offset + 12 > len(data) or data[offset + 4:offset + 8] != bytes(4):
        raise PngValidationError('ICC curve header is truncated or has nonzero reserved bytes')
    kind = data[offset:offset + 4]
    if kind == b'curv':
        count, = unpack_from('>I', data, offset + 8)
        end = offset + 12 + 2 * count
    elif kind == b'para':
        function, reserved = unpack_from('>HH', data, offset + 8)
        counts = (1, 3, 4, 5, 7)
        if function >= len(counts) or reserved:
            raise PngValidationError('ICC parametric curve function or reserved bytes are invalid')
        end = offset + 12 + 4 * counts[function]
    else:
        raise PngValidationError('ICC LUT curves require curv or para encoding')
    if end > len(data):
        raise PngValidationError('ICC curve count exceeds the available data')
    return end


def validate_lut(data: bytes) -> None:
    kind = data[:4]
    minimum = 52 if kind == b'mft2' else 48 if kind == b'mft1' else 32
    if len(data) < minimum:
        raise PngValidationError('ICC LUT header is truncated')
    inputs, outputs = data[8:10]
    # ICC.1 colour encodings contain at most fifteen components (Table 19).
    if not 1 <= inputs <= 15 or not 1 <= outputs <= 15:
        raise PngValidationError('ICC LUT channel counts must be between 1 and 15')
    if kind in (b'mft1', b'mft2'):
        if data[11] or data[10] < 2:
            raise PngValidationError('ICC LUT grid or reserved byte is invalid')
        if kind == b'mft1':
            expected = 48 + 256 * (inputs + outputs) + data[10] ** inputs * outputs
        else:
            in_entries, out_entries = unpack_from('>HH', data, 48)
            if not 2 <= in_entries <= 4096 or not 2 <= out_entries <= 4096:
                raise PngValidationError('ICC LUT16 table counts must be between 2 and 4096')
            expected = 52 + 2 * (in_entries * inputs + data[10] ** inputs * outputs + out_entries * outputs)
        if len(data) != expected:
            raise PngValidationError('ICC LUT table sizes do not match the tag size')
        return

    if data[10:12] != bytes(2):
        raise PngValidationError('ICC LUT reserved bytes must be zero')
    b_curves, matrix, m_curves, clut, a_curves = unpack_from('>5I', data, 12)
    if not b_curves or bool(matrix) != bool(m_curves) or bool(clut) != bool(a_curves):
        raise PngValidationError('ICC LUT processing element combination is invalid')
    if inputs != outputs and not clut:
        raise PngValidationError('ICC LUT with different channel counts requires a CLUT')
    for offset in (b_curves, matrix, m_curves, clut, a_curves):
        if offset and (offset < 32 or offset % 4 or offset >= len(data)):
            raise PngValidationError('ICC LUT element offset is invalid')
    reverse = kind == b'mBA '
    middle_channels = inputs if reverse else outputs
    if matrix and (middle_channels != 3 or matrix + 48 > len(data)):
        raise PngValidationError('ICC LUT matrix needs three M curves and twelve coefficients')

    # Check each individual curve once, including when two groups share a suffix.
    checked: dict[int, int] = {}
    for offset, count in ((b_curves, middle_channels), (m_curves, middle_channels),
                          (a_curves, outputs if reverse else inputs)):
        if not offset:
            continue
        for index in range(count):
            end = checked.get(offset)
            if end is None:
                end = curve_end(data, offset)
                checked[offset] = end
            padded = (end + 3) & ~3
            if any(data[end:min(padded, len(data))]):
                raise PngValidationError('ICC LUT curve padding must be zero')
            if index + 1 < count and padded > len(data):
                raise PngValidationError('ICC LUT curve padding exceeds the tag')
            offset = padded

    if clut:
        if clut + 20 > len(data):
            raise PngValidationError('ICC LUT CLUT header is truncated')
        grid = data[clut:clut + inputs]
        precision = data[clut + 16]
        if any(points < 2 for points in grid) or any(data[clut + inputs:clut + 16]):
            raise PngValidationError('ICC LUT CLUT grid or unused dimensions are invalid')
        if precision not in (1, 2) or any(data[clut + 17:clut + 20]):
            raise PngValidationError('ICC LUT CLUT precision or reserved bytes are invalid')
        if clut + 20 + prod(grid) * outputs * precision > len(data):
            raise PngValidationError('ICC LUT CLUT data exceeds the tag')


def validate_lut_context(profile: bytes, signature: bytes, data: bytes | memoryview) -> None:
    """Check the channel counts/direction for the standard transform tags."""
    device, pcs = profile[16:20], profile[20:24]
    if signature in (b'A2B0', b'A2B1', b'A2B2'):
        source, target = device, pcs
        expected = (_channels(source), _channels(target))
        pcs_input = profile[12:16] == b'abst' and source == b'XYZ '
    elif signature in (b'B2A0', b'B2A1', b'B2A2'):
        source, target = pcs, device
        expected = (_channels(source), _channels(target))
        pcs_input = profile[12:16] != b'link' and source == b'XYZ '
    elif signature == b'gamt':
        expected = (_channels(pcs), 1)
        pcs_input = pcs == b'XYZ '
    elif signature in (b'pre0', b'pre1', b'pre2'):
        expected = (_channels(pcs), _channels(pcs))
        pcs_input = pcs == b'XYZ '
    else:
        return
    if tuple(data[8:10]) != expected:
        raise PngValidationError(f'ICC {signature!r} LUT channel counts disagree with the profile')
    if data[:4] in (b'mft1', b'mft2') and not pcs_input:
        if unpack_from('>9i', data, 12) != _IDENTITY:
            raise PngValidationError('ICC legacy LUT matrix must be identity unless its input is PCSXYZ')
    if data[:4] == b'mBA ' and pcs not in (b'XYZ ', b'Lab '):
        raise PngValidationError('ICC mBA LUT requires XYZ or Lab PCS')


def _channels(signature: bytes) -> int:
    if signature == b'GRAY':
        return 1
    if signature == b'CMYK':
        return 4
    if signature in (b'XYZ ', b'Lab ', b'Luv ', b'YCbr', b'Yxy ', b'RGB ', b'HSV ', b'HLS ', b'CMY '):
        return 3
    if signature[1:] == b'CLR' and signature[:1] in b'23456789ABCDEF':
        return int(signature[:1], 16)
    raise PngValidationError(f'ICC LUT uses an unrecognized colour space {signature!r}')
