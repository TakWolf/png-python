"""Checks for opaque ICC and Exif payloads, without color transforms."""

from struct import unpack_from

from png._exif import validate_exif_structure
from png._icc_header import validate_header_fields
from png._icc_collections import validate_dictionary, validate_response_curves
from png._icc_lut import LUT_TYPES, _channels, curve_end, validate_lut, validate_lut_context
from png._icc_mpet import MPET_TAGS, validate_mpet, validate_mpet_context
from png._icc_misc import MISC_TYPES, V4_TAG_TYPES, validate_misc, validate_misc_context
from png._icc_records import (
    validate_colorant_context,
    validate_colorant_table,
    validate_named_colors,
    validate_profile_identifiers,
    validate_profile_sequence,
)
from png._icc_text import ascii_terminated, description_end, multilingual_end
from png.error import PngUnsupportedError, PngValidationError


def validate_icc_structure(profile: bytes) -> None:
    if not isinstance(profile, bytes) or len(profile) < 132:
        raise PngValidationError('ICC profile requires a header and tag count')
    if profile[36:40] != b'acsp':
        raise PngValidationError('ICC profile requires the acsp header signature')
    (declared,) = unpack_from('>I', profile)
    if declared != len(profile):
        raise PngValidationError(f'ICC declared size {declared} does not match {len(profile)} payload bytes')
    (count,) = unpack_from('>I', profile, 128)
    table_end = 132 + count * 12
    if table_end > len(profile):
        raise PngValidationError('ICC tag table exceeds the profile')
    signatures = set()
    ranges = set()
    for index in range(count):
        signature, offset, size = unpack_from('>4sII', profile, 132 + index * 12)
        if signature in signatures:
            raise PngValidationError('duplicate ICC tag signature')
        signatures.add(signature)
        if offset % 4 or offset < table_end:
            raise PngValidationError('ICC tag offset must be aligned and follow the tag table')
        if size < 8 or offset + size > len(profile):
            raise PngValidationError('ICC tag data exceeds the profile or lacks its type header')
        if profile[offset + 4 : offset + 8] != bytes(4):
            raise PngValidationError('ICC tag type reserved bytes must be zero')
        ranges.add((offset, offset + size))
    previous_end = table_end
    for start, end in sorted(ranges):
        if start < previous_end:
            raise PngValidationError('ICC tag data must not partially overlap')
        if profile[8] == 4:
            # ICC v4 requires contiguous elements with up to three zero pad bytes.
            if start != ((previous_end + 3) & ~3) or any(profile[previous_end:start]):
                raise PngValidationError('ICC v4 tag data has gaps or nonzero padding')
        previous_end = end
    if profile[8] == 4:
        if len(profile) != ((previous_end + 3) & ~3) or any(profile[previous_end:]):
            raise PngValidationError('ICC v4 final padding or profile extent is invalid')


_ICC_MATRIX_TAGS = frozenset((b'rXYZ', b'gXYZ', b'bXYZ', b'rTRC', b'gTRC', b'bTRC'))
_ICC_SINGLE_XYZ_TAGS = frozenset((b'wtpt', b'bkpt', b'lumi', b'rXYZ', b'gXYZ', b'bXYZ'))
_ICC_TRC_TAGS = frozenset((b'kTRC', b'rTRC', b'gTRC', b'bTRC'))


def validate_icc_tags(profile: bytes) -> None:
    """Check common required tags and selected tag encodings, not all ICC semantics."""
    validate_icc_structure(profile)
    version = profile[8]
    if version not in (2, 4):
        raise PngUnsupportedError(f'ICC version {version} tag requirements are not supported')
    profile_class = profile[12:16]
    if profile_class not in (b'scnr', b'mntr', b'prtr', b'link', b'spac', b'abst', b'nmcl'):
        raise PngValidationError('ICC profile class is not recognized')
    validate_header_fields(profile)
    (count,) = unpack_from('>I', profile, 128)
    tags = {}
    offsets = {}
    checked = set()
    for index in range(count):
        signature, offset, size = unpack_from('>4sII', profile, 132 + index * 12)
        kind = profile[offset : offset + 4]
        tags[signature] = kind
        offsets[signature] = offset
        allowed = None
        if signature == b'desc':
            allowed = (b'mluc',) if version == 4 else (b'desc',)
        elif signature == b'cprt':
            allowed = (b'mluc',) if version == 4 else (b'text',)
        elif signature in _ICC_SINGLE_XYZ_TAGS:
            allowed = (b'XYZ ',)
            if size != 20:
                raise PngValidationError(f'ICC {signature!r} requires one XYZ value')
        elif signature in _ICC_TRC_TAGS:
            allowed = (b'curv', b'para') if version == 4 else (b'curv',)
        elif signature == b'chad':
            allowed = (b'sf32',)
            if size != 44:
                raise PngValidationError('ICC chad requires a nine-element matrix')
            if version == 4:
                a, b, c, d, e, f, g, h, i = unpack_from('>9i', profile, offset + 8)
                if a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g) == 0:
                    raise PngValidationError('ICC chad matrix must be invertible')
        elif signature in (b'A2B0', b'A2B1', b'A2B2'):
            allowed = (b'mft1', b'mft2', b'mAB ') if version == 4 else (b'mft1', b'mft2')
        elif signature in (b'B2A0', b'B2A1', b'B2A2', b'gamt'):
            allowed = (b'mft1', b'mft2', b'mBA ') if version == 4 else (b'mft1', b'mft2')
        elif signature in (b'pseq', b'ncl2') or (version == 4 and signature == b'psid'):
            allowed = (signature,)
        elif version == 4 and signature in (b'clrt', b'clot'):
            allowed = (b'clrt',)
        elif version == 4 and signature in V4_TAG_TYPES:
            allowed = V4_TAG_TYPES[signature]
        elif version == 4 and signature in (b'meta', b'resp'):
            allowed = (b'dict',) if signature == b'meta' else (b'rcs2',)
        elif version == 4 and signature in MPET_TAGS:
            allowed = (b'mpet',)
        if allowed is not None and kind not in allowed:
            raise PngValidationError(f'ICC {signature!r} has an invalid tag type {kind!r}')
        extent = (offset, size)
        if extent not in checked:
            _validate_icc_tag_data(profile[offset : offset + size])
            checked.add(extent)
        if kind in LUT_TYPES:
            validate_lut_context(profile, signature, memoryview(profile)[offset : offset + size])
        elif kind == b'mpet':
            validate_mpet_context(profile, signature, memoryview(profile)[offset : offset + size])
        elif version == 4 and kind == b'clrt':
            validate_colorant_context(profile, signature, memoryview(profile)[offset : offset + size])
        if version == 4 and (kind in MISC_TYPES or signature == b'targ'):
            validate_misc_context(profile, signature, memoryview(profile)[offset : offset + size])
        if version == 4 and signature == b'resp':
            if unpack_from('>H', profile, offset + 8)[0] != _channels(profile[16:20]):
                raise PngValidationError('ICC response curve channels disagree with the device')

    required = {b'desc', b'cprt'}
    if profile_class != b'link':
        required.add(b'wtpt')
    # ICC.1:2001-04 supplies v2 requirements; ICC.1:2022 supplies v4's.
    # In particular, the v2 RGB display matrix tags are still required when
    # optional LUTs are present. V4 instead permits a separate LUT-only model.
    if profile_class in (b'scnr', b'mntr', b'prtr'):
        if profile[16:20] == b'GRAY':
            required.add(b'kTRC')
        elif profile_class == b'prtr':
            required.update((b'A2B0', b'A2B1', b'A2B2', b'B2A0', b'B2A1', b'B2A2', b'gamt'))
        elif version == 2 and profile_class == b'mntr':
            required.update(_ICC_MATRIX_TAGS)
            if profile[20:24] == b'Lab ' and not any(
                tag in tags for tag in (b'A2B0', b'A2B1', b'A2B2', b'B2A0', b'B2A1', b'B2A2')
            ):
                raise PngValidationError('ICC v2 Lab display requires an A2B or B2A LUT tag')
        elif _channels(profile[16:20]) == 3 and _ICC_MATRIX_TAGS.issubset(tags) and profile[20:24] == b'XYZ ':
            pass  # The input/v4 display matrix model is an alternative to a LUT.
        else:
            required.add(b'A2B0')
            if profile_class == b'mntr':
                required.add(b'B2A0')
    elif profile_class == b'spac':
        required.update((b'A2B0', b'B2A0'))
    elif profile_class == b'link':
        required.update((b'A2B0', b'pseq'))
    elif profile_class == b'abst':
        required.add(b'A2B0')
    elif profile_class == b'nmcl':
        required.add(b'ncl2')
    missing = required.difference(tags)
    if version == 4:
        if b'ciis' in tags:
            state = profile[offsets[b'ciis'] + 8 : offsets[b'ciis'] + 12]
            if state not in (b'scoe', b'sape', b'fpce', b'rhoc', b'rpoc'):
                raise PngValidationError('ICC colorimetric image state is reserved')
            missing.update({b'view'}.difference(tags))
            if state in (b'rhoc', b'rpoc'):
                missing.update({b'chad'}.difference(tags))
            elif b'view' in tags:
                x, y, z = unpack_from('>3i', profile, offsets[b'view'] + 8)
                # These ciis states explicitly identify view's illuminant as
                # the source adopted white. Generic viewing metadata alone
                # does not establish the original measurement conditions.
                if y > 0 and ((10000 * x + y // 2) // y, (10000 * z + y // 2) // y) != (9642, 8249):
                    missing.update({b'chad'}.difference(tags))
        if profile_class == b'mntr' and b'wtpt' in tags:
            white = unpack_from('>3i', profile, offsets[b'wtpt'] + 8)
            if tuple((value * 10000 + 32768) // 65536 for value in white) != (9642, 10000, 8249):
                raise PngValidationError('ICC v4 display media white must be the PCS illuminant')
        if profile_class in (b'prtr', b'link') and profile[17:20] == b'CLR':
            missing.update({b'clrt'}.difference(tags))
        if profile_class == b'link' and profile[21:24] == b'CLR':
            missing.update({b'clot'}.difference(tags))
    if missing:
        raise PngValidationError(f'ICC required tags are missing: {sorted(missing)!r}')


def _validate_icc_tag_data(data: bytes) -> None:
    kind = data[:4]
    size = len(data)
    if kind == b'dict':
        validate_dictionary(data)
    elif kind == b'rcs2':
        validate_response_curves(data)
    elif kind in MISC_TYPES:
        validate_misc(data)
    elif kind in (b'curv', b'para'):
        if curve_end(data) != size:
            raise PngValidationError('ICC curve count does not match tag size')
    elif kind in LUT_TYPES:
        validate_lut(data)
    elif kind == b'mpet':
        validate_mpet(data)
    elif kind == b'ncl2':
        validate_named_colors(data)
    elif kind == b'clrt':
        validate_colorant_table(data)
    elif kind == b'pseq':
        validate_profile_sequence(data)
    elif kind == b'psid':
        validate_profile_identifiers(data)
    elif kind == b'XYZ ':
        if size < 20 or (size - 8) % 12:
            raise PngValidationError('ICC XYZ array has an invalid size')
    elif kind == b'sf32':
        if (size - 8) % 4:
            raise PngValidationError('ICC fixed-point array has an invalid size')
    elif kind == b'text':
        ascii_terminated(memoryview(data)[8:])
    elif kind == b'desc':
        if description_end(memoryview(data)) != size:
            raise PngValidationError('ICC description Unicode or ScriptCode extent is invalid')
    elif kind == b'mluc':
        multilingual_end(memoryview(data))
