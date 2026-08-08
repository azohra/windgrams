import struct

from windgrams.geotiff import parse_geotiff_grid


def test_reads_uncompressed_float_geotiff_cells_by_latitude_and_longitude():
    grid = parse_geotiff_grid(make_geotiff())

    assert grid.width == 2
    assert grid.height == 2
    assert grid.value_at(49.95, -117.95) == 10
    assert grid.value_at(49.95, -117.85) == 20
    assert grid.value_at(49.85, -117.95) == 30
    assert grid.value_at(49.85, -117.85) == 40
    assert grid.value_at(50.2, -117.95) is None


def make_geotiff() -> bytes:
    tag_count = 11
    ifd_offset = 8
    ifd_length = 2 + tag_count * 12 + 4
    pixel_scale_offset = ifd_offset + ifd_length
    tiepoint_offset = pixel_scale_offset + 24
    pixels_offset = tiepoint_offset + 48
    buffer = bytearray(pixels_offset + 16)

    struct.pack_into("<2sH I", buffer, 0, b"II", 42, ifd_offset)
    struct.pack_into("<H", buffer, ifd_offset, tag_count)

    def tag(index: int, number: int, tag_type: int, count: int, value: int) -> None:
        offset = ifd_offset + 2 + index * 12
        struct.pack_into("<HHI", buffer, offset, number, tag_type, count)
        if tag_type == 3 and count == 1:
            struct.pack_into("<H", buffer, offset + 8, value)
        else:
            struct.pack_into("<I", buffer, offset + 8, value)

    tag(0, 256, 3, 1, 2)
    tag(1, 257, 3, 1, 2)
    tag(2, 258, 3, 1, 32)
    tag(3, 259, 3, 1, 1)
    tag(4, 273, 4, 1, pixels_offset)
    tag(5, 277, 3, 1, 1)
    tag(6, 278, 3, 1, 2)
    tag(7, 279, 4, 1, 16)
    tag(8, 339, 3, 1, 3)
    tag(9, 33550, 12, 3, pixel_scale_offset)
    tag(10, 33922, 12, 6, tiepoint_offset)

    struct.pack_into("<ddd", buffer, pixel_scale_offset, 0.1, 0.1, 0.0)
    struct.pack_into("<dddddd", buffer, tiepoint_offset, 0.0, 0.0, 0.0, -118.0, 50.0, 0.0)
    for pixel, value in enumerate([10.0, 20.0, 30.0, 40.0]):
        struct.pack_into("<f", buffer, pixels_offset + pixel * 4, value)
    return bytes(buffer)
