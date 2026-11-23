"""Mutable unpacked sample rows, with optional compact integer storage."""

from array import array

PngRow = list[int] | bytearray | array
PngBitmap = list[PngRow]
