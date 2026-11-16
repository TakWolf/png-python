"""ICC header field checks used after envelope and version validation."""

from hashlib import md5
from struct import unpack_from

from png._icc_lut import _channels
from png.error import PngUnsupportedError, PngValidationError


def validate_header_fields(profile: bytes) -> None:
    _channels(profile[16:20])
    if profile[12:16] == b'link':
        _channels(profile[20:24])
    if profile[12:16] == b'abst' and profile[16:20] not in (b'XYZ ', b'Lab '):
        raise PngValidationError('ICC Abstract profiles transform PCS to PCS')
    minor = profile[9]
    if (minor >> 4) > 9 or (minor & 15) > 9 or any(profile[10:12]):
        raise PngValidationError('ICC version requires BCD digits and zero reserved bytes')
    if profile[12:16] != b'link' and profile[20:24] not in (b'XYZ ', b'Lab '):
        raise PngValidationError('ICC PCS must be XYZ or Lab for a non-DeviceLink profile')
    _, month, day, hour, minute, second = unpack_from('>6H', profile, 24)
    # The ICC dateTimeNumber field uses an unsigned 16-bit year, not datetime's
    # narrower 1..9999 range. Check the field ranges stated in its definition.
    if not 1 <= month <= 12 or not 1 <= day <= 31 or hour > 23 or minute > 59 or second > 59:
        raise PngValidationError('ICC creation date/time fields are outside their ranges')
    (intent,) = unpack_from('>I', profile, 64)
    if intent > 3:
        raise PngValidationError('ICC rendering intent must be between 0 and 3')
    illuminant = unpack_from('>3i', profile, 68)
    # ICC specifies values rounded to four decimal places, not one fixed binary
    # encoding. Integer rounding preserves all permitted neighbouring encodings.
    if tuple((value * 10000 + 32768) // 65536 for value in illuminant) != (9642, 10000, 8249):
        raise PngValidationError('ICC PCS illuminant must round to D50')
    if profile[8] == 4:
        if profile[40:44] not in (bytes(4), b'APPL', b'MSFT', b'SGI ', b'SUNW'):
            raise PngValidationError('ICC v4 primary platform uses an undefined signature')
        (attributes,) = unpack_from('>Q', profile, 56)
        if attributes & 0xFFFFFFF0:
            raise PngValidationError('ICC v4 device attribute reserved bits must be zero')
    if any(profile[100:128]):
        raise PngValidationError('ICC header reserved bytes must be zero')

    # ICC's guidance on making v2 profiles explicitly recommends the same ID
    # field/calculation as v4. A zero ID is allowed; a present one must match.
    if any(profile[84:100]):
        digest = md5(usedforsecurity=False)
        view = memoryview(profile)
        for part in (view[:44], bytes(4), view[48:64], bytes(4), view[68:84], bytes(16), view[100:]):
            digest.update(part)
        if digest.digest() != profile[84:100]:
            raise PngValidationError('ICC Profile ID does not match the profile data')
    if profile[8] == 4:
        _validate_registrations(profile)


def _validate_registrations(profile: bytes) -> None:
    # ICC.1:2022 7.2.3/12/13 require registered signatures. 7.2.17 only
    # recommends registration for the creator, so it is deliberately excluded.
    from png._icc_registry_data import CMM, DEVICES, MANUFACTURERS

    for name, signature, registered in (('CMM', profile[4:8], CMM), ('manufacturer', profile[48:52], MANUFACTURERS)):
        if any(signature) and signature not in registered:
            raise PngUnsupportedError(
                f'ICC {name} {signature!r} cannot be confirmed by the 2026-11-16 registry snapshot'
            )
    maker, model = profile[48:52], profile[52:56]
    if any(model):
        if any(maker):
            known = (maker, model) in DEVICES
        else:
            known = any(registered_model == model for _, registered_model in DEVICES)
        if not known:
            raise PngUnsupportedError(
                f'ICC device {maker!r}/{model!r} cannot be confirmed by the 2026-11-16 registry snapshot'
            )


def validate_png_embedding(profile: bytes) -> None:
    if profile[12:16] in (b'link', b'abst'):
        raise PngValidationError('ICC DeviceLink and Abstract profiles cannot be embedded in PNG images')
