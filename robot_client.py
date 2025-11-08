from __future__ import annotations
import subprocess
import threading
from traceback import format_exc
import socketio
import time
from robot_config import ROBOT_ID, ROBOT_NAME, SERVER_URL, ROBOT_VERSION
from findee import Findee
from pathlib import Path

# 서버 연결 객체
sio = socketio.Client()
stop_flag = False
running_thread = None

# 위젯 데이터 저장 (로봇은 단일 세션이므로 세션 ID 불필요)
slider_data = {}   # {widget_id: [values]}
pid_data = {}      # {widget_id: {'p': float, 'i': float, 'd': float}}
gesture_data = {}  # {widget_id: gesture}

#region 로봇 연결 이벤트
# 연결 성공: 로봇 등록 요청
@sio.event
def connect():
    print("<서버에 로봇 등록 요청>")
    print(f"ID              : {ROBOT_ID}")
    print(f"Name            : {ROBOT_NAME}")
    print(f"Version         : {ROBOT_VERSION}")
    print(f"Session ID      : {sio.sid}")
    print("====================")
    # 로봇 > 서버
    sio.emit('robot_connected', {'robot_id': ROBOT_ID, 'robot_name': ROBOT_NAME, 'robot_version': ROBOT_VERSION})

@sio.event
def robot_registered(data):
    print(f"로봇 등록 성공: {data.get('message')}") if data.get('success') else print(f"로봇 등록 실패: {data.get('error')}")

# 연결 끊김: 5초 마다 재연결 시도
@sio.event
def disconnect():
    def reconnect_loop():
        while not sio.connected:
            try:
                threading.Timer(5.0, lambda: sio.connect(SERVER_URL)).start()
            except Exception:
                pass
    threading.Thread(target=reconnect_loop, daemon=True).start()

def heartbeat():
    if sio.connected: sio.emit('robot_heartbeat', {'robot_id': ROBOT_ID})
#endregion

#region 로봇 코드 실행
def exec_code(code, session_id):
    global stop_flag, running_thread
    stop_flag = False

    def check_stop_flag(func):
        def wrapper(*args, **kwargs):
            if stop_flag: return
            return func(*args, **kwargs)
        return wrapper

    @check_stop_flag
    def realtime_print(*args, **kwargs):
        output = ' '.join(str(arg) for arg in args)
        if output: sio.emit('robot_stdout', {'session_id': session_id, 'output': output})

    try:
        @check_stop_flag
        def emit_image(image, widget_id):
            if hasattr(image, 'shape'):  # numpy 배열인지 확인
                import cv2
                ok, buffer = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if not ok:
                    return
                sio.emit('robot_emit_image', {'session_id': session_id, 'image_data': buffer.tobytes(), 'widget_id': widget_id})
            else:
                print(f"이미지가 numpy 배열이 아님 - 타입: {type(image)}")

        @check_stop_flag
        def emit_text(text, widget_id):
            sio.emit('robot_emit_text', {'session_id': session_id, 'text': text, 'widget_id': widget_id})

        # 위젯 데이터 조회 함수들
        def get_slider_value(widget_id, default=None):
            """슬라이더 위젯의 값을 가져옴"""
            return slider_data.get(widget_id, default)
        
        def get_pid_value(widget_id, default=None):
            """PID 위젯의 값을 가져옴 (p, i, d)"""
            if default is None:
                default = {'p': 0.0, 'i': 0.0, 'd': 0.0}
            return pid_data.get(widget_id, default)
        
        def get_gesture_value(widget_id, default=None):
            """제스처 위젯의 값을 가져옴"""
            return gesture_data.get(widget_id, default)

        exec_namespace = {
            'Findee': Findee,
            'emit_image': emit_image,
            'emit_text': emit_text,
            'get_slider_value': get_slider_value,
            'get_pid_value': get_pid_value,
            'get_gesture_value': get_gesture_value,
            'print': realtime_print
        }
        compiled_code = compile(code, '<string>', 'exec')
        exec(compiled_code, exec_namespace)
    except Exception:
        # 오류 출력
        for line in format_exc().splitlines():
            sio.emit('robot_stderr', {'session_id': session_id, 'output': line})
    finally:
        # 추적 딕셔너리에서 제거
        running_thread = None
        stop_flag = False
        print(f"DEBUG: Session {session_id}: 스레드 정리 완료")
        sio.emit('robot_finished', {'session_id': session_id})

@sio.event
def execute_code(data):
    global running_thread
    try:
        code = data.get('code', '')
        session_id = data.get('session_id', '')
        thread = threading.Thread(target=exec_code, args=(code, session_id), daemon=True)
        running_thread = thread
        thread.start()
    except Exception as e:
        sio.emit('robot_stderr', {'session_id': session_id, 'output': f'코드 실행 중 오류가 발생했습니다: {str(e)}'})

@sio.event
def slider_update(data):
    """슬라이더 업데이트 데이터 수신"""
    try:
        widget_id = data.get('widget_id')
        values = data.get('values')
        
        if widget_id and values is not None:
            slider_data[widget_id] = values
    except Exception as e:
        print(f"슬라이더 업데이트 처리 오류: {e}")

@sio.event
def pid_update(data):
    """PID 업데이트 데이터 수신"""
    try:
        widget_id = data.get('widget_id')
        p = data.get('p', 0.0)
        i = data.get('i', 0.0)
        d = data.get('d', 0.0)
        
        if widget_id:
            pid_data[widget_id] = {'p': p, 'i': i, 'd': d}
    except Exception as e:
        print(f"PID 업데이트 처리 오류: {e}")

@sio.event
def gesture_update(data):
    """제스처 업데이트 데이터 수신"""
    try:
        widget_id = data.get('widget_id')
        gesture = data.get('gesture') or data.get('data')
        
        if widget_id and gesture is not None:
            gesture_data[widget_id] = gesture
    except Exception as e:
        print(f"제스처 업데이트 처리 오류: {e}")

@sio.event
def stop_execution(data):
    global running_thread, stop_flag
    try:
        session_id = data.get('session_id', '')
        thread = running_thread
        stop_flag = True

        if thread is None:
            sio.emit('robot_stderr', {'session_id': session_id, 'output': '실행 중인 코드가 없습니다.'})
            return

        if thread.is_alive():
            def raise_in_thread(thread, exc_type = SystemExit):
                import ctypes
                if thread is None or not thread.is_alive():
                    return False

                func = ctypes.pythonapi.PyThreadState_SetAsyncExc
                func.argtypes = [ctypes.c_ulong, ctypes.py_object]
                func.restype = ctypes.c_int

                tid = ctypes.c_ulong(thread.ident)
                res = func(tid, ctypes.py_object(exc_type))

                if res > 1:
                    func(tid, ctypes.py_object(0))
                    return False
                return res == 1

            raise_in_thread(thread, SystemExit)
            thread.join(timeout=1.0)

            running_thread = None
            stop_flag = False
    except Exception as e:
        sio.emit('robot_stderr', {'session_id': session_id, 'output': f'코드 중지 중 오류가 발생했습니다: {str(e)}'})
#endregion

#region 로봇 업데이트/초기화
def force_git_pull(ScriptDir):
    # 로컬 변경사항을 stash로 저장 및 Git pull 실행
    subprocess.run(['git', 'stash', 'push', '-m', '"Temp"'], capture_output=True, text=True, cwd=str(ScriptDir))
    subprocess.run(['git', 'pull', 'origin', 'main'], capture_output=True, text=True, cwd=str(ScriptDir))

@sio.event
def client_update(data):
    import subprocess, re
    try:
        ScriptDir = Path(__file__).parent.absolute() # 현재 파일의 디렉토리
        RobotID, RobotName = ROBOT_ID, ROBOT_NAME # 현재 로봇 설정 저장
        force_git_pull(ScriptDir) # 강제 Git pull
        # 로봇 설정 복원
        subprocess.run(f"sed -i 's/ROBOT_ID = .*/ROBOT_ID = \"{RobotID}\"/' {ScriptDir}/robot_config.py", shell=True, check=True)
        subprocess.run(f"sed -i 's/ROBOT_NAME = .*/ROBOT_NAME = \"{RobotName}\"/' {ScriptDir}/robot_config.py", shell=True, check=True)
        # 서비스 재시작
        subprocess.Popen(['sudo', 'systemctl', 'restart', 'robot_client.service'], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        pass
    except Exception as e:
        pass

@sio.event
def client_reset(data):
    subprocess.run("echo 'MODE=AP' | sudo tee /etc/pf_env", shell=True, check=True) # /etc/pf_env 파일 수정
    ScriptDir = Path(__file__).parent.absolute() # 현재 파일의 디렉토리
    force_git_pull(ScriptDir)
    subprocess.Popen(["sudo", "reboot"]) # 재부팅
#endregion

if __name__ == "__main__":
    try:
        sio.connect(SERVER_URL)
        while True:
            heartbeat()
            time.sleep(5)
    except KeyboardInterrupt:
        sio.disconnect()