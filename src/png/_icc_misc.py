"""Selected ICC scalar/array encodings and optional-tag contexts."""

from struct import unpack_from

from png._icc_lut import _channels
from png._icc_text import ascii_terminated
from png.error import PngUnsupportedError, PngValidationError

ARRAY_WIDTHS = {b'uf32': 4, b'ui08': 1, b'ui16': 2, b'ui32': 4, b'ui64': 8}
MISC_TYPES = frozenset(ARRAY_WIDTHS) | {b'data', b'dtim', b'sig ', b'meas', b'view', b'chrm', b'clro', b'cicp'}
V4_TAG_TYPES = {
    b'chrm': (b'chrm',), b'clro': (b'clro',), b'cicp': (b'cicp',),
    b'meas': (b'meas',), b'view': (b'view',), b'calt': (b'dtim',), b'targ': (b'text',),
    b'tech': (b'sig ',), b'ciis': (b'sig ',), b'rig0': (b'sig ',), b'rig2': (b'sig ',),
    b'dmnd': (b'mluc',), b'dmdd': (b'mluc',), b'vued': (b'mluc',),
    b'pre0': (b'mft1', b'mft2', b'mAB ', b'mBA '),
    b'pre1': (b'mft1', b'mft2', b'mBA '), b'pre2': (b'mft1', b'mft2', b'mBA '),
}

# ICC.1:2022 9.2.39/9.2.48 Tables 27/28 and 9.2.49 Table 29.
# These are tag-context values, not a whitelist for arbitrary signatureType data.
_TECHNOLOGIES = frozenset((
    b'fscn', b'dcam', b'rscn', b'ijet', b'twax', b'epho', b'esta', b'dsub',
    b'rpho', b'fprn', b'vidm', b'vidc', b'pjtv', b'CRT ', b'PMD ', b'AMD ',
    b'LCD ', b'OLED', b'KPCD', b'imgs', b'grav', b'offs', b'silk', b'flex',
    b'mpfs', b'mpfr', b'dmpc', b'dcpj',
))


def validate_misc(data: bytes) -> None:
    kind, size = data[:4], len(data)
    if kind in ARRAY_WIDTHS:
        if (size - 8) % ARRAY_WIDTHS[kind]:
            raise PngValidationError('ICC numeric array has an incomplete value')
        return
    fixed = {b'dtim': 20, b'sig ': 12, b'meas': 36, b'view': 36, b'cicp': 12}
    if size < 12 or (kind in fixed and size != fixed[kind]):
        raise PngValidationError('ICC optional tag has an invalid size')
    if kind == b'data':
        flag, = unpack_from('>I', data, 8)
        if flag > 1:
            raise PngValidationError('ICC data flag must identify ASCII or binary data')
        if flag == 0:
            ascii_terminated(memoryview(data)[12:])
    elif kind == b'dtim':
        _, month, day, hour, minute, second = unpack_from('>6H', data, 8)
        if not 1 <= month <= 12 or not 1 <= day <= 31 or hour > 23 or minute > 59 or second > 59:
            raise PngValidationError('ICC dateTime fields are outside their ranges')
    elif kind == b'meas':
        observer, = unpack_from('>I', data, 8)
        geometry, = unpack_from('>I', data, 24)
        illuminant, = unpack_from('>I', data, 32)
        if observer > 2 or geometry > 2 or illuminant > 8:
            raise PngValidationError('ICC measurement encoding is not defined')
    elif kind == b'view':
        if unpack_from('>I', data, 32)[0] > 8:
            raise PngValidationError('ICC viewing illuminant is not defined')
    elif kind == b'cicp':
        from png._color_codes import validate_code_points
        validate_code_points(*data[8:12])
        if data[11] > 1:
            raise PngValidationError('ICC cicp full range flag must be zero or one')
    elif kind == b'clro':
        count, = unpack_from('>I', data, 8)
        if size != 12 + count or len(set(data[12:])) != count:
            raise PngValidationError('ICC colorant order count or repeated colorants are invalid')
    elif kind == b'chrm':
        count, encoding = unpack_from('>HH', data, 8)
        if size != 12 + 8 * count:
            raise PngValidationError('ICC chromaticity channel count disagrees with its size')
        # The normative matching requirement explicitly names encodings 1..4.
        standard = {
            1: (640, 330, 300, 600, 150, 60), 2: (630, 340, 310, 595, 155, 70),
            3: (640, 330, 290, 600, 150, 60), 4: (625, 340, 280, 605, 155, 70),
        }
        if encoding in standard:
            if count != 3 or tuple((v * 1000 + 32768) // 65536 for v in unpack_from('>6I', data, 12)) != standard[encoding]:
                raise PngValidationError('ICC standard phosphor chromaticities disagree with its encoding')


def validate_misc_context(profile: bytes, signature: bytes, data: memoryview) -> None:
    if signature == b'targ':
        text = data[8:].tobytes()
        if len(text) < 8:
            raise PngValidationError('ICC characterization target requires a seven-character identifier')
        if text[:7] == b'ICCHDAT' and (text[7:8] != b' ' or len(text) < 10 or b'\0' in text[8:-1]):
            raise PngValidationError('ICC ICCHDAT target requires a space and reference name')
        if text[:7] == b'ICCHDAT':
            from png._icc_registry_data import CHARACTERIZATION
            if text[8:-1] not in CHARACTERIZATION:
                raise PngUnsupportedError('ICC target name cannot be confirmed by the 2026-11-16 registry snapshot')
    if signature == b'tech' and bytes(data[8:12]) not in _TECHNOLOGIES:
        raise PngValidationError('ICC technology signature is not defined in ICC.1:2022')
    if signature in (b'rig0', b'rig2') and data[8:12] != b'prmg':
        raise PngValidationError('ICC reference medium gamut signature must be prmg in ICC.1:2022')
    if signature == b'clro' and unpack_from('>I', data, 8)[0] != _channels(profile[16:20]):
        raise PngValidationError('ICC colorant order count disagrees with the data color space')
    if signature == b'cicp':
        device = profile[16:20]
        if profile[12:16] not in (b'scnr', b'mntr') or device not in (b'RGB ', b'XYZ ', b'YCbr'):
            raise PngValidationError('ICC cicp is only permitted for input/display RGB, XYZ or YCbCr')
        if (device == b'YCbr') != (data[10] != 0):
            raise PngValidationError('ICC cicp matrix coefficients disagree with the data color space')
