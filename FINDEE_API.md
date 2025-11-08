# Findee 모듈 사용자 가이드

Findee 모듈은 라즈베리파이 기반 자율주행 자동차의 하드웨어를 제어하는 Python 모듈입니다.

## 모듈 임포트

```python
from findee import Findee
```

## Findee 객체 생성

Findee는 싱글톤 패턴을 사용하므로, 어디서든 `Findee()`를 호출하면 같은 인스턴스를 반환합니다.

```python
findee = Findee()
```

---

## 모터 제어 함수

### 기본 이동 함수

#### `move_forward(speed, duration)`
로봇을 전진시킵니다.

**파라미터:**
- `speed` (float, 기본값: 80.0): 속도 (20~100 범위)
- `duration` (float, 기본값: 0.0): 이동 시간 (초). 0이면 계속 이동, 0보다 크면 지정 시간 후 자동 정지

**사용 예:**
```python
findee.move_forward(80, 2.0)  # 80 속도로 2초 전진
findee.move_forward()          # 기본 속도로 계속 전진
```

---

#### `move_backward(speed, duration)`
로봇을 후진시킵니다.

**파라미터:**
- `speed` (float, 기본값: 80.0): 속도 (20~100 범위)
- `duration` (float, 기본값: 0.0): 이동 시간 (초)

**사용 예:**
```python
findee.move_backward(70, 1.5)  # 70 속도로 1.5초 후진
```

---

### 회전 함수

#### `turn_left(speed, duration)`
로봇을 제자리에서 왼쪽으로 회전시킵니다.

**파라미터:**
- `speed` (float, 기본값: 80.0): 회전 속도 (20~100 범위)
- `duration` (float, 기본값: 0.0): 회전 시간 (초)

**사용 예:**
```python
findee.turn_left(80, 1.0)  # 1초 동안 왼쪽으로 회전
```

---

#### `turn_right(speed, duration)`
로봇을 제자리에서 오른쪽으로 회전시킵니다.

**파라미터:**
- `speed` (float, 기본값: 80.0): 회전 속도 (20~100 범위)
- `duration` (float, 기본값: 0.0): 회전 시간 (초)

**사용 예:**
```python
findee.turn_right(80, 1.0)  # 1초 동안 오른쪽으로 회전
```

---

### 곡선 이동 함수

#### `curve_left(speed, angle, duration)`
로봇을 왼쪽으로 곡선 이동시킵니다.

**파라미터:**
- `speed` (float, 기본값: 80.0): 속도 (20~100 범위)
- `angle` (int, 기본값: 60): 곡선 각도 (0~60 범위)
- `duration` (float, 기본값: 0.0): 이동 시간 (초)

**사용 예:**
```python
findee.curve_left(80, 45, 2.0)  # 45도 각도로 왼쪽 곡선 이동
```

---

#### `curve_right(speed, angle, duration)`
로봇을 오른쪽으로 곡선 이동시킵니다.

**파라미터:**
- `speed` (float, 기본값: 80.0): 속도 (20~100 범위)
- `angle` (int, 기본값: 60): 곡선 각도 (0~60 범위)
- `duration` (float, 기본값: 0.0): 이동 시간 (초)

**사용 예:**
```python
findee.curve_right(80, 45, 2.0)  # 45도 각도로 오른쪽 곡선 이동
```

---

### 정지 함수

#### `stop()`
로봇을 즉시 정지시킵니다.

**사용 예:**
```python
findee.stop()
```

---

## 초음파 센서 함수

### `get_distance()`
초음파 센서를 사용하여 앞쪽 장애물까지의 거리를 측정합니다.

**반환값:**
- `float`: 거리 (cm). 측정 성공 시 0 이상의 값
- `-1`: Trig 타임아웃 (센서 초기화 실패)
- `-2`: Echo 타임아웃 (반사 신호 수신 실패)

**사용 예:**
```python
distance = findee.get_distance()
if distance > 0:
    print(f"앞에 장애물이 {distance}cm 떨어져 있습니다.")
elif distance == -1:
    print("센서 초기화 실패")
elif distance == -2:
    print("센서 신호 수신 실패")
```

---

## 카메라 함수

### `get_frame()`
카메라에서 현재 프레임을 캡처합니다.

**반환값:**
- `numpy.ndarray`: RGB 이미지 배열 (numpy 배열)

**사용 예:**
```python
frame = findee.get_frame()
# frame은 numpy 배열이므로 OpenCV나 다른 이미지 처리 라이브러리에서 사용 가능
```

---

### `set_fps(fps)`
카메라의 FPS(초당 프레임 수)를 설정합니다.

**파라미터:**
- `fps` (int): 설정할 FPS 값 (1~60 범위)

**사용 예:**
```python
findee.set_fps(30)  # 30 FPS로 설정
```

---

### `set_resolution(resolution)`
카메라의 해상도를 설정합니다.

**파라미터:**
- `resolution` (tuple[int, int]): (너비, 높이) 튜플

**사용 예:**
```python
findee.set_resolution((640, 480))   # 640x480 해상도
findee.set_resolution((1280, 720))  # 1280x720 해상도
```

---

## 주의사항

1. **속도 범위**: 모터 속도는 자동으로 20~100 범위로 제한됩니다.
2. **싱글톤 패턴**: Findee 객체는 어디서든 같은 인스턴스를 반환하므로, 여러 번 생성해도 동일한 객체입니다.
3. **자동 정리**: 프로그램 종료 시 자동으로 GPIO와 카메라 리소스가 정리됩니다.
4. **카메라 프레임**: `get_frame()`으로 받은 프레임은 numpy 배열이므로, OpenCV나 다른 이미지 처리 라이브러리와 함께 사용할 수 있습니다.

---

## 함수 목록

사용 가능한 모든 함수 목록입니다.

### 모터 제어
- `move_forward(speed, duration)` - 전진
- `move_backward(speed, duration)` - 후진
- `turn_left(speed, duration)` - 왼쪽 회전
- `turn_right(speed, duration)` - 오른쪽 회전
- `curve_left(speed, angle, duration)` - 왼쪽 곡선
- `curve_right(speed, angle, duration)` - 오른쪽 곡선
- `stop()` - 정지

### 초음파 센서
- `get_distance()` - 거리 측정

### 카메라
- `get_frame()` - 프레임 캡처
- `set_fps(fps)` - FPS 설정
- `set_resolution(resolution)` - 해상도 설정
