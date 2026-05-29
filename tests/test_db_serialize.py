import struct

from mnemo_mcp.db import _STRUCT_CACHE, _serialize_f32


def test_serialize_f32_default():
    """Test serialization with default target_dims (0)."""
    vec = [1.0, 2.0, 3.0]
    expected = struct.pack("3f", *vec)
    assert _serialize_f32(vec) == expected
    assert len(_serialize_f32(vec)) == 12


def test_serialize_f32_truncate():
    """Test truncation when input vector is longer than target_dims."""
    vec = [1.0, 2.0, 3.0, 4.0]
    target_dims = 2
    expected = struct.pack("2f", 1.0, 2.0)
    assert _serialize_f32(vec, target_dims) == expected
    assert len(_serialize_f32(vec, target_dims)) == 8


def test_serialize_f32_padding():
    """Test zero-padding when input vector is shorter than target_dims."""
    vec = [1.0, 2.0]
    target_dims = 4
    expected = struct.pack("4f", 1.0, 2.0, 0.0, 0.0)
    assert _serialize_f32(vec, target_dims) == expected
    assert len(_serialize_f32(vec, target_dims)) == 16


def test_serialize_f32_exact():
    """Test serialization when input vector length exactly matches target_dims."""
    vec = [1.0, 2.0, 3.0]
    target_dims = 3
    expected = struct.pack("3f", *vec)
    assert _serialize_f32(vec, target_dims) == expected


def test_serialize_f32_empty():
    """Test serialization of an empty list."""
    vec = []
    expected = b""
    assert _serialize_f32(vec) == expected


def test_serialize_f32_empty_with_target():
    """Test serialization of an empty list with target_dims > 0."""
    vec = []
    target_dims = 2
    expected = struct.pack("2f", 0.0, 0.0)
    assert _serialize_f32(vec, target_dims) == expected


def test_serialize_f32_cache_behavior():
    """Verify that struct.Struct instances are cached in _STRUCT_CACHE."""
    # Ensure we use a dimension that might not be in cache yet or verify it enters it
    dims = 123
    vec = [0.0] * dims

    if dims in _STRUCT_CACHE:
        del _STRUCT_CACHE[dims]

    _serialize_f32(vec)

    assert dims in _STRUCT_CACHE
    assert isinstance(_STRUCT_CACHE[dims], struct.Struct)
    assert _STRUCT_CACHE[dims].format == f"{dims}f"


def test_serialize_f32_reuses_cache():
    """Verify that _serialize_f32 reuses the cached Struct instance."""
    dims = 5
    vec = [1.0] * dims

    _serialize_f32(vec)
    first_struct = _STRUCT_CACHE[dims]

    _serialize_f32(vec)
    second_struct = _STRUCT_CACHE[dims]

    assert first_struct is second_struct
