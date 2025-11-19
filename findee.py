from __future__ import annotations

#TODO: 모터, 이동 함수
#TODO: 카메라, 캡쳐 함수
#TODO: 초음파, 거리 측정 함수
#TODO: 함수명.

import os
import time
import atexit
import json
from pathlib import Path

import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR) # Werkzeug 로거 비활성화
logging.getLogger('picamera2').setLevel(logging.ERROR) # Picamera2 로거 비활성화
os.environ['LIBCAMERA_LOG_FILE'] = '/dev/null' # disable logging

import RPi.GPIO as GPIO
from picamera2 import Picamera2
# from picamera2.encoders import JpegEncoder
import cv2

USE_DEBUG = True



def debug_decorator(func):
    def wrapper(*args, **kwargs):
        if USE_DEBUG: print(f"DEBUG: {func.__name__} Called")
        try:
            ret = func(*args, **kwargs)
        except Exception as e:
            if USE_DEBUG: print(f"DEBUG: ERR:{e}")
            ret = -99
        return ret
    return wrapper

class Findee:
    default_speed: float = 80.0
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Findee, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self, safe_mode: bool = False):
        if self._initialized: return
        self._initialized = True

        # self.thread_lock = threading.Lock()

        self.gpio_init()
        self.camera_init()

        # 캘리브레이션 자동 로드
        self._load_calibration()

        atexit.register(self.cleanup)

#region: init
    @debug_decorator
    def gpio_init(self):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)

        # Pin Number
        self.IN1: int = 23 # Right Motor Direction 1
        self.IN2: int = 24 # Right Motor Direction 2
        self.ENA: int = 12 # Right Motor PWM
        self.IN3: int = 22 # Left Motor Direction 1
        self.IN4: int = 27 # Left Motor Direction 2
        self.ENB: int = 13 # Left Motor PWM
        self.TRIG: int = 5 # Ultrasonic Sensor Trigger
        self.ECHO: int = 6 # Ultrasonic Sensor Echo

        # GPIO Pin Setting
        GPIO.setup((self.IN1, self.IN2, self.ENA,
                    self.IN3, self.IN4, self.ENB,
                    self.TRIG), GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(self.ECHO, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        self.rightPWM = GPIO.PWM(self.ENA, 1000)
        self.rightPWM.start(0)
        self.leftPWM = GPIO.PWM(self.ENB, 1000)
        self.leftPWM.start(0)

    @debug_decorator
    def camera_init(self):
        # Camera Init
        self.camera = Picamera2()
        self.config = self.camera.create_video_configuration(
            main={"size": (640, 480), "format": "RGB888"},
            controls={"FrameDurationLimits": (33333, 33333)},
            queue=False, buffer_count=2
        )
        self.camera.configure(self.config)
        self.camera.start()
#endregion

#region: Motor
    @debug_decorator
    def changePin(self, IN1, IN2, IN3, IN4, ENA, ENB):
        self.IN1 = IN1 if IN1 is not None else self.IN1
        self.IN2 = IN2 if IN2 is not None else self.IN2
        self.IN3 = IN3 if IN3 is not None else self.IN3
        self.IN4 = IN4 if IN4 is not None else self.IN4
        self.ENA = ENA if ENA is not None else self.ENA
        self.ENB = ENB if ENB is not None else self.ENB

    @staticmethod
    def constrain(value, min_value, max_value):
        return max(min(value, max_value), min_value)

    def calibrate_motors(self, dir: int = 1, low_speed_ratio: float = 0.88,
                         high_speed_ratio: float = 0.58, save_to_file: bool = True):
        """
        모터 속도별 보정 비율 설정 및 파일 저장

        Args:
            dir: 빠른 바퀴 방향 (0: 왼쪽이 빠름, 1: 오른쪽이 빠름)
            low_speed_ratio: 속도 30에서의 비율 (기본 0.88)
            high_speed_ratio: 속도 100에서의 비율 (기본 0.58)
            save_to_file: 파일에 저장할지 여부 (기본 True)
        """
        self.motor_calibration = {
            'dir': dir,
            'low_speed_ratio': low_speed_ratio,
            'high_speed_ratio': high_speed_ratio
        }

        if save_to_file:
            self._save_calibration()
            # 저장 후 파일에서 다시 로드하여 검증
            self._load_calibration()

        dir_name = "왼쪽" if dir == 0 else "오른쪽"
        print(f"모터 캘리브레이션 설정 완료:")
        print(f"  빠른 바퀴: {dir_name}")
        print(f"  속도 30: 비율 {low_speed_ratio}")
        print(f"  속도 100: 비율 {high_speed_ratio}")
        print(f"  (중간 속도는 선형 보간으로 자동 계산됩니다)")

    def _save_calibration(self):
        """캘리브레이션 값을 파일에 저장 (~/.config/findee/motor_calibration.json)"""
        try:
            cal_dir = Path.home() / '.config' / 'findee'
            cal_dir.mkdir(parents=True, exist_ok=True)
            cal_file = cal_dir / 'motor_calibration.json'

            with open(cal_file, 'w') as f:
                json.dump(self.motor_calibration, f, indent=2)
            print(f"캘리브레이션 저장 완료: {cal_file}")
        except Exception as e:
            print(f"캘리브레이션 저장 실패: {e}")

    def _load_calibration(self):
        """파일에서 캘리브레이션 값 로드"""
        try:
            cal_file = Path.home() / '.config' / 'findee' / 'motor_calibration.json'
            if cal_file.exists():
                with open(cal_file, 'r') as f:
                    self.motor_calibration = json.load(f)
                print(f"캘리브레이션 로드 완료: {cal_file}")
                return True
        except Exception as e:
            print(f"캘리브레이션 로드 실패: {e}")
        return False

    def _get_motor_ratio(self, speed: float) -> float:
        """속도에 따른 동적 보정 비율 계산 (선형 보간, 30-100 고정)"""
        if not hasattr(self, 'motor_calibration'):
            return 1.0  # 캘리브레이션 없으면 보정 안 함

        cal = self.motor_calibration
        low_ratio = cal['low_speed_ratio']
        high_ratio = cal['high_speed_ratio']

        abs_speed = abs(speed)

        # 속도 30 이하
        if abs_speed <= 30:
            return low_ratio

        # 속도 100 이상
        if abs_speed >= 100:
            return high_ratio

        # 중간 속도: 선형 보간 (30-100)
        # y = low_ratio + (high_ratio - low_ratio) * (speed - 30) / 70
        ratio = low_ratio + (high_ratio - low_ratio) * (abs_speed - 30) / 70.0
        return ratio


    def _apply_calibration(self, left: float, right: float) -> tuple[float, float]:
        """캘리브레이션 보정을 적용하여 left, right 값을 반환"""
        if not hasattr(self, 'motor_calibration'):
            return left, right

        cal = self.motor_calibration
        dir = cal.get('dir', 1)  # 기본값: 오른쪽이 빠름

        if dir == 1:
            # 오른쪽이 빠름: 왼쪽(느린 쪽) 값을 그대로, 오른쪽에 왼쪽 값에 맞는 비율 적용
            ratio = self._get_motor_ratio(abs(left))
            return left, right * ratio
        elif dir == 0:
            # 왼쪽이 빠름: 오른쪽(느린 쪽) 값을 그대로, 왼쪽에 오른쪽 값에 맞는 비율 적용
            ratio = self._get_motor_ratio(abs(right))
            return left * ratio, right

        return left, right

    def control_motors(self, left : float, right : float) -> bool:
        #TODO: time.sleep이 모터 제어에 영향을 주는지 확인해야 함.

        # 속도 값 정규화 (동시에 처리하기 위해 미리 계산)
        if right == 0.0:
            right_normalized = 0.0
        else:
            right_normalized = (1 if right >= 0 else -1) * self.constrain(abs(right), 20, 100)

        if left == 0.0:
            left_normalized = 0.0
        else:
            left_normalized = (1 if left >= 0 else -1) * self.constrain(abs(left), 20, 100)

        # 오른쪽 모터 제어
        if right_normalized == 0.0:
            self.rightPWM.ChangeDutyCycle(0.0)
            GPIO.output((self.IN1, self.IN2), GPIO.LOW)
        else:
            # 100%로 먼저 설정 (강한 토크)
            self.rightPWM.ChangeDutyCycle(100.0)
            # OUT1(HIGH) -> OUT2(LOW) : Forward
            GPIO.output(self.IN1, GPIO.HIGH if right_normalized > 0 else GPIO.LOW)
            GPIO.output(self.IN2, GPIO.LOW if right_normalized > 0 else GPIO.HIGH)

        # 왼쪽 모터 제어
        if left_normalized == 0.0:
            self.leftPWM.ChangeDutyCycle(0.0)
            GPIO.output((self.IN3, self.IN4), GPIO.LOW)
        else:
            # 100%로 먼저 설정 (강한 토크)
            self.leftPWM.ChangeDutyCycle(100.0)
            # OUT4(HIGH) -> OUT3(LOW) : Forward
            GPIO.output(self.IN4, GPIO.HIGH if left_normalized > 0 else GPIO.LOW)
            GPIO.output(self.IN3, GPIO.LOW if left_normalized > 0 else GPIO.HIGH)

        # 두 모터 모두 100%로 설정된 후 동시에 대기
        if right_normalized != 0.0 or left_normalized != 0.0:
            time.sleep(0.02)

        # 두 모터 모두 실제 속도로 동시에 변경
        if right_normalized != 0.0:
            self.rightPWM.ChangeDutyCycle(abs(right_normalized))
        if left_normalized != 0.0:
            self.leftPWM.ChangeDutyCycle(abs(left_normalized))

    # Stop
    @debug_decorator
    def stop(self):
        self.control_motors(0.0, 0.0)

    # Straight, Backward
    @debug_decorator
    def move_forward(self, speed : float = default_speed, duration : float = 0.0):
        left, right = self._apply_calibration(speed, speed)
        self.control_motors(left, right)
        self.__duration_check(duration)

    @debug_decorator
    def move_backward(self, speed : float = default_speed, duration : float = 0.0):
        left, right = self._apply_calibration(-speed, -speed)
        self.control_motors(left, right)
        self.__duration_check(duration)

    # Rotation
    @debug_decorator
    def turn_left(self, speed : float = default_speed, duration : float = 0.0):
        # 회전 시에도 캘리브레이션 적용 (양쪽 방향 회전 속도 일관성 유지)
        left, right = self._apply_calibration(-speed, speed)
        self.control_motors(left, right)
        self.__duration_check(duration)

    @debug_decorator
    def turn_right(self, speed : float = default_speed, duration : float = 0.0):
        # 회전 시에도 캘리브레이션 적용 (양쪽 방향 회전 속도 일관성 유지)
        left, right = self._apply_calibration(speed, -speed)
        self.control_motors(left, right)
        self.__duration_check(duration)

    # Curvilinear Rotation
    @debug_decorator
    def curve_left(self, speed : float = default_speed, angle : int = 60, duration : float = 0.0):
        angle = self.constrain(angle, 0, 60)
        ratio = 1.0 - (angle / 60.0) * 0.5
        left, right = self._apply_calibration(speed * ratio, speed)
        self.control_motors(left, right)
        self.__duration_check(duration)

    @debug_decorator
    def curve_right(self, speed : float = default_speed, angle : int = 60, duration : float = 0.0):
        angle = self.constrain(angle, 0, 60)
        ratio = 1.0 - (angle / 60.0) * 0.5
        left, right = self._apply_calibration(speed, speed * ratio)
        self.control_motors(left, right)
        self.__duration_check(duration)

    def __duration_check(self, duration: float):
        if duration < 0.0:
            raise ValueError("Duration must be greater or equal to 0.0")
        elif duration > 0.0:
            time.sleep(duration); self.stop()
        else:
            return
#endregion

#region: Ultrasonic Sensor
    @debug_decorator
    def get_distance(self):
        # Return
        # -1 : Trig Timeout
        # -2 : Echo Timeout
        # Trigger
        GPIO.output(self.TRIG, GPIO.HIGH)
        time.sleep(0.00001)
        GPIO.output(self.TRIG, GPIO.LOW)

        # Measure Distance
        t1 = time.time()
        while GPIO.input(self.ECHO) is not GPIO.HIGH:
            if time.time() - t1 > 0.1: # 100ms
                return -1

        t1 = time.time()

        while GPIO.input(self.ECHO) is not GPIO.LOW:
            if time.time() - t1 > 0.03: # 30ms
                return -2

        t2 = time.time()

        # Measure Success
        distance = ((t2 - t1) * 34300) / 2
        return round(distance, 1)
#endregion

#region: Cameras
    def get_frame(self):
        return self.camera.capture_array("main").copy()

    def mjpeg_gen(self):
        while True:
            # RGB 프레임 -> BGR로 변환(OpenCV는 BGR 기준)
            arr = self.camera.capture_array("main").copy()

            ok, buf = cv2.imencode('.jpg', arr, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if not ok:
                continue
            jpg = buf.tobytes()

            yield (b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" +
                jpg + b"\r\n")

            # 과도한 CPU 점유 방지
            time.sleep(0.001)

    @debug_decorator
    def set_fps(self, fps: int):
        if fps <= 0:
            print("DEBUG: ERR: FPS는 0보다 커야 합니다.")
            return
        elif fps > 60:
            print("DEBUG: ERR: FPS는 60 이하여야 합니다.")
            return

        frame_duration = 1000000 // fps
        current_controls = self.camera.camera_controls
        current_controls["FrameDurationLimits"] = (frame_duration, frame_duration)

        self.camera.stop()
        self.camera.set_controls(current_controls)
        self.camera.start()

        print(f"DEBUG: 카메라 FPS가 약 {fps}로 변경되었습니다.")

    @debug_decorator
    def set_resolution(self, resolution: tuple[int, int]):
        if self.config["main"]["size"] == resolution:
            return

        new_config = self.config.copy()
        new_config["main"]["size"] = resolution

        self.camera.stop()
        self.camera.configure(new_config)
        self.camera.start()

        self.config = new_config

        print(f"DEBUG: 카메라 해상도가 {resolution}으로 변경되었습니다.")
#endregion

#region: others
    @debug_decorator
    def cleanup(self):
        # GPIO Cleanup
        self.control_motors(0.0, 0.0)
        if hasattr(self, 'rightPWM'): self.rightPWM.stop()
        if hasattr(self, 'leftPWM'): self.leftPWM.stop()
        GPIO.output((self.IN1, self.IN2, self.ENA, self.IN3, self.IN4,
                    self.ENB, self.TRIG), GPIO.LOW)
        GPIO.cleanup()

        # Camera Cleanup
        if hasattr(self, 'camera'):
            if hasattr(self.camera, 'stop'):
                self.camera.stop()
            if hasattr(self.camera, 'close'):
                self.camera.close()
            del self.camera

        Findee._instance = None
        Findee._initialized = False

        del self
#endregion


if __name__ == "__main__":
    findee = Findee()
    for i in range(20):
        print(findee.get_distance())
        time.sleep(0.1)
    # try:
    #     findee = Findee()

    #     # 객체 생성 성공 후에만 실행
    #     findee.move_forward(100, 1.0)
    #     a = Findee()

    #     print("=== __dict__ 사용 ===")
    #     for attr_name, attr_value in findee.__dict__.items():
    #         print(f"{attr_name}: {attr_value}")

    # except Exception as e:
    #     print(f"Error: {e}")
    #     print("객체 생성에 실패했습니다.")