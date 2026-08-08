"""Reads the single-band float32 GeoTIFFs GeoMet's WCS returns.

Deliberately minimal: uncompressed strips, one sample per pixel, nearest-cell
lookup. Anything else is an upstream change worth failing loudly on.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

TAG_IMAGE_WIDTH = 256
TAG_IMAGE_HEIGHT = 257
TAG_BITS_PER_SAMPLE = 258
TAG_COMPRESSION = 259
TAG_STRIP_OFFSETS = 273
TAG_SAMPLES_PER_PIXEL = 277
TAG_ROWS_PER_STRIP = 278
TAG_STRIP_BYTE_COUNTS = 279
TAG_SAMPLE_FORMAT = 339
TAG_MODEL_PIXEL_SCALE = 33550
TAG_MODEL_TIEPOINT = 33922
TAG_GDAL_NODATA = 42113

_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 11: 4, 12: 8}


@dataclass(frozen=True)
class GeoTiffGrid:
    width: int
    height: int
    _buffer: bytes
    _byte_order: str
    _strip_offsets: list[int]
    _strip_byte_counts: list[int]
    _rows_per_strip: int
    _pixel_width: float
    _pixel_height: float
    _raster_x: float
    _raster_y: float
    _tie_longitude: float
    _tie_latitude: float
    _no_data: float | None

    def value_at(self, latitude: float, longitude: float) -> float | None:
        column = math.floor((longitude - self._tie_longitude) / self._pixel_width + self._raster_x)
        row = math.floor((self._tie_latitude - latitude) / self._pixel_height + self._raster_y)
        if column < 0 or column >= self.width or row < 0 or row >= self.height:
            return None

        strip_index = row // self._rows_per_strip
        if strip_index >= len(self._strip_offsets):
            return None
        strip_offset = self._strip_offsets[strip_index]
        strip_byte_count = self._strip_byte_counts[strip_index]
        row_in_strip = row % self._rows_per_strip
        value_offset = strip_offset + (row_in_strip * self.width + column) * 4
        if value_offset + 4 > strip_offset + strip_byte_count or value_offset + 4 > len(
            self._buffer
        ):
            return None
        (value,) = struct.unpack_from(f"{self._byte_order}f", self._buffer, value_offset)
        if not math.isfinite(value) or value <= -3e38:
            return None
        if self._no_data is not None and value == self._no_data:
            return None
        return value


def parse_geotiff_grid(buffer: bytes) -> GeoTiffGrid:
    if len(buffer) < 16:
        raise ValueError("GeoMet returned a truncated GeoTIFF")
    if buffer[0:2] == b"II":
        order = "<"
    elif buffer[0:2] == b"MM":
        order = ">"
    else:
        raise ValueError("Invalid GeoTIFF byte order")
    (magic,) = struct.unpack_from(f"{order}H", buffer, 2)
    if magic != 42:
        raise ValueError("Unsupported TIFF format")

    (ifd_offset,) = struct.unpack_from(f"{order}I", buffer, 4)
    (tag_count,) = struct.unpack_from(f"{order}H", buffer, ifd_offset)
    tags: dict[int, tuple[int, int, int]] = {}
    for index in range(tag_count):
        offset = ifd_offset + 2 + index * 12
        tag_number, tag_type, count = struct.unpack_from(f"{order}HHI", buffer, offset)
        type_size = _TYPE_SIZES.get(tag_type)
        if type_size is None:
            continue
        if type_size * count <= 4:
            value_offset = offset + 8
        else:
            (value_offset,) = struct.unpack_from(f"{order}I", buffer, offset + 8)
        tags[tag_number] = (tag_type, count, value_offset)

    def values(tag_number: int) -> list[float | int | str]:
        tag = tags.get(tag_number)
        if tag is None:
            raise ValueError(f"GeoTIFF tag {tag_number} is missing")
        tag_type, count, value_offset = tag
        output: list[float | int | str] = []
        type_size = _TYPE_SIZES[tag_type]
        for index in range(count):
            offset = value_offset + index * type_size
            if tag_type == 1:
                output.append(buffer[offset])
            elif tag_type == 2:
                output.append(chr(buffer[offset]))
            elif tag_type == 3:
                output.append(struct.unpack_from(f"{order}H", buffer, offset)[0])
            elif tag_type == 4:
                output.append(struct.unpack_from(f"{order}I", buffer, offset)[0])
            elif tag_type == 5:
                numerator, denominator = struct.unpack_from(f"{order}II", buffer, offset)
                output.append(numerator / denominator)
            elif tag_type == 11:
                output.append(struct.unpack_from(f"{order}f", buffer, offset)[0])
            elif tag_type == 12:
                output.append(struct.unpack_from(f"{order}d", buffer, offset)[0])
        return output

    def scalar(tag_number: int) -> float | int:
        value = values(tag_number)[0]
        if not isinstance(value, (int, float)):
            raise ValueError(f"GeoTIFF tag {tag_number} is missing")
        return value

    width = int(scalar(TAG_IMAGE_WIDTH))
    height = int(scalar(TAG_IMAGE_HEIGHT))
    if (
        scalar(TAG_BITS_PER_SAMPLE) != 32
        or scalar(TAG_COMPRESSION) != 1
        or scalar(TAG_SAMPLES_PER_PIXEL) != 1
        or scalar(TAG_SAMPLE_FORMAT) != 3
    ):
        raise ValueError("GeoMet returned an unsupported GeoTIFF encoding")

    strip_offsets = [int(value) for value in values(TAG_STRIP_OFFSETS)]
    strip_byte_counts = [int(value) for value in values(TAG_STRIP_BYTE_COUNTS)]
    rows_per_strip = int(scalar(TAG_ROWS_PER_STRIP))
    pixel_scale = values(TAG_MODEL_PIXEL_SCALE)
    tiepoints = [float(value) for value in values(TAG_MODEL_TIEPOINT)]
    if len(pixel_scale) < 2 or len(tiepoints) < 6 or not strip_offsets:
        raise ValueError("GeoMet GeoTIFF is missing its geographic grid")
    pixel_width = float(pixel_scale[0])
    pixel_height = float(pixel_scale[1])
    if not math.isfinite(pixel_width) or not math.isfinite(pixel_height):
        raise ValueError("GeoMet GeoTIFF is missing its geographic grid")

    no_data: float | None = None
    no_data_tag = tags.get(TAG_GDAL_NODATA)
    if no_data_tag is not None and no_data_tag[0] == 2:
        text = "".join(
            chr(byte)
            for byte in buffer[no_data_tag[2] : no_data_tag[2] + no_data_tag[1]].split(b"\0")[0]
        )
        try:
            no_data = float(text)
        except ValueError:
            no_data = None

    return GeoTiffGrid(
        width=width,
        height=height,
        _buffer=buffer,
        _byte_order=order,
        _strip_offsets=strip_offsets,
        _strip_byte_counts=strip_byte_counts,
        _rows_per_strip=rows_per_strip,
        _pixel_width=pixel_width,
        _pixel_height=pixel_height,
        _raster_x=tiepoints[0],
        _raster_y=tiepoints[1],
        _tie_longitude=tiepoints[3],
        _tie_latitude=tiepoints[4],
        _no_data=no_data,
    )
