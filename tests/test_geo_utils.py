import math

from geo_utils import haversine


def test_haversine_zero_distance_same_point():
    assert haversine(25.033, 121.565, 25.033, 121.565) == 0.0


def test_haversine_equator_one_degree():
    # 赤道上經度差 1 度的弧長有精確解析解: R * radians(1)
    expected = 6371000 * math.radians(1)
    result = haversine(0.0, 0.0, 0.0, 1.0)
    assert abs(result - expected) < 1.0  # 誤差 1 公尺內
