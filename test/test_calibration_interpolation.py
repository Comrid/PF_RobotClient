# 보간 알고리즘 테스트

def _get_motor_ratio(speed: float, low_ratio: float, high_ratio: float) -> float:
    """속도에 따른 동적 보정 비율 계산 (선형 보간, 30-100 고정)"""
    abs_speed = abs(speed)
    
    # 속도 30 이하
    if abs_speed <= 30:
        return low_ratio
    
    # 속도 100 이상
    if abs_speed >= 100:
        return high_ratio
    
    # 중간 속도: 선형 보간 (30-100)
    # y = low_ratio + (high_ratio - low_ratio) * (speed - 30) / 70
    ratio = low_ratio + (high_ratio - low_ratio) * (abs_speed - 30) / 70
    return ratio

# 테스트 케이스 1
print("=== 테스트 케이스 1: RATIOS = [0.88, 0.65] ===")
low_ratio = 0.88
high_ratio = 0.65

for speed in [30, 50, 70, 100]:
    ratio = _get_motor_ratio(speed, low_ratio, high_ratio)
    right_speed = speed * ratio
    print(f"속도 {speed}: ratio={ratio:.3f}, 오른쪽={right_speed:.1f}, 차이={speed-right_speed:.1f}")

print("\n=== 테스트 케이스 2: RATIOS = [0.88, 0.15] ===")
low_ratio = 0.88
high_ratio = 0.15

for speed in [30, 50, 70, 100]:
    ratio = _get_motor_ratio(speed, low_ratio, high_ratio)
    right_speed = speed * ratio
    print(f"속도 {speed}: ratio={ratio:.3f}, 오른쪽={right_speed:.1f}, 차이={speed-right_speed:.1f}")

