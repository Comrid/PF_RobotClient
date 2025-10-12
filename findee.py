from __future__ import annotations

#TODO: 모터, 이동 함수
#TODO: 카메라, 캡쳐 함수
#TODO: 초음파, 거리 측정 함수
#TODO: 함수명.

import os
import time
import atexit

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

    def control_motors(self, left : float, right : float) -> bool:
        #TODO: time.sleep이 모터 제어에 영향을 주는지 확인해야 함.
        #-Right Motor Control-#
        if right == 0.0:
            self.rightPWM.ChangeDutyCycle(0.0)
            GPIO.output((self.IN1, self.IN2), GPIO.LOW)
        else:
            right = (1 if right >= 0 else -1) * self.constrain(abs(right), 20, 100)
            self.rightPWM.ChangeDutyCycle(100.0) # 100% for strong torque at first time
            # OUT1(HIGH) -> OUT2(LOW) : Forward
            GPIO.output(self.IN1, GPIO.HIGH if right > 0 else GPIO.LOW)
            GPIO.output(self.IN2, GPIO.LOW if right > 0 else GPIO.HIGH)
            time.sleep(0.02)
            self.rightPWM.ChangeDutyCycle(abs(right))

        #-Left Motor Control-#
        if left == 0.0:
            self.leftPWM.ChangeDutyCycle(0.0)
            GPIO.output((self.IN3, self.IN4), GPIO.LOW)
        else:
            left = (1 if left >= 0 else -1) * self.constrain(abs(left), 20, 100)
            self.leftPWM.ChangeDutyCycle(100.0) # 100% for strong torque at first time
            # OUT4(HIGH) -> OUT3(LOW) : Forward
            GPIO.output(self.IN4, GPIO.HIGH if left > 0 else GPIO.LOW)
            GPIO.output(self.IN3, GPIO.LOW if left > 0 else GPIO.HIGH)
            time.sleep(0.02)
            self.leftPWM.ChangeDutyCycle(abs(left))

    # Stop
    @debug_decorator
    def stop(self):
        self.control_motors(0.0, 0.0)

    # Straight, Backward
    @debug_decorator
    def move_forward(self, speed : float = default_speed, duration : float = 0.0):
        self.control_motors(speed, speed)
        self.__duration_check(duration)

    @debug_decorator
    def move_backward(self, speed : float = default_speed, duration : float = 0.0):
        self.control_motors(-speed, -speed)
        self.__duration_check(duration)

    # Rotation
    @debug_decorator
    def turn_left(self, speed : float = default_speed, duration : float = 0.0):
        self.control_motors(speed, -speed)
        self.__duration_check(duration)

    @debug_decorator
    def turn_right(self, speed : float = default_speed, duration : float = 0.0):
        self.control_motors(-speed, speed)
        self.__duration_check(duration)

    # Curvilinear Rotation
    @debug_decorator
    def curve_left(self, speed : float = default_speed, angle : int = 60, duration : float = 0.0):
        angle = self.constrain(angle, 0, 60)
        ratio = 1.0 - (angle / 60.0) * 0.5
        self.control_motors(speed, speed * ratio)
        self.__duration_check(duration)

    @debug_decorator
    def curve_right(self, speed : float = default_speed, angle : int = 60, duration : float = 0.0):
        angle = self.constrain(angle, 0, 60)
        ratio = 1.0 - (angle / 60.0) * 0.5
        self.control_motors(speed * ratio, speed)
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