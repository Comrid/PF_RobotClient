#TODO 로봇 커스텀 함수 관리

from __future__ import annotations
import threading
from traceback import format_exc
import socketio
import time
from robot_config import ROBOT_ID, ROBOT_NAME, SERVER_URL, HARDWARE_ENABLED, ROBOT_VERSION
try:
    from findee import Findee
except Exception:
    Findee = None

stop_flag = False
running_thread = None

sio = socketio.Client()

robot_status = {
    'connected': False,
    'executing_code': False,
    'current_session': None
}

Findee = None

# 연결 성공: 로봇 등록 요청
@sio.event
def connect():
    robot_status['connected'] = True

    # 서버에 로봇 등록
    print("📤 서버에 로봇 등록 요청 전송...")
    sio.emit('robot_connected', { # 로봇 > 서버
        'robot_id': ROBOT_ID,
        'robot_name': ROBOT_NAME,
        'hardware_enabled': HARDWARE_ENABLED,
        'robot_version': ROBOT_VERSION
    })

@sio.event
def robot_registered(data):
    if data.get('success'):
        print(f"로봇 등록 성공: {data.get('message')}")
    else:
        print(f"로봇 등록 실패: {data.get('error')}")

# 연결 끊김: 5초 마다 재연결 시도
@sio.event
def disconnect():
    def reconnect_loop():
        while not sio.connected:
            try:
                threading.Timer(5.0, sio.connect(SERVER_URL)).start()
            except Exception:
                pass
    threading.Thread(target=reconnect_loop, daemon=True).start()

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
        if output:
            sio.emit('robot_stdout', {
                'session_id': session_id,
                'output': output
            })

    try:
        @check_stop_flag
        def emit_image(image, widget_id):
            debug_on = True
            if debug_on: print(f"DEBUG: emit_image 호출됨 : {widget_id}")
            if hasattr(image, 'shape'):  # numpy 배열인지 확인
                import time
                import cv2
                start_time = time.time()

                ok, buffer = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if not ok:
                    if debug_on: print("DEBUG: JPEG 인코딩 실패")
                    return

                # sio.emit() 사용 - 바이너리 첨부 전송
                sio.emit('robot_emit_image', {
                    'session_id': session_id,
                    'image_data': buffer.tobytes(),
                    'widget_id': widget_id
                })

                total_time = time.time() - start_time
                if debug_on: print(f"DEBUG: 이미지 메시지 전송 완료 - 총 시간: {total_time*1000:.2f}ms")
            else:
                print(f"DEBUG: 이미지가 numpy 배열이 아님 - 타입: {type(image)}")

        @check_stop_flag
        def emit_text(text, widget_id):
            sio.emit('robot_emit_text', {
                'session_id': session_id,
                'text': text,
                'widget_id': widget_id
            })

        exec_namespace = {
            'sio': sio,
            'session_id': session_id,
            'stop_flag': stop_flag,
            'Findee': Findee,
            'emit_image': emit_image,
            'emit_text': emit_text,
            'print': realtime_print
        }
        compiled_code = compile(code, '<string>', 'exec')
        exec(compiled_code, exec_namespace)
    except Exception:
        # 오류 출력
        for line in format_exc().splitlines():
            sio.emit('robot_stderr', {
                'session_id': session_id,
                'output': line
            })
    finally:
        # 추적 딕셔너리에서 제거
        running_thread = None
        stop_flag = False
        print(f"DEBUG: Session {session_id}: 스레드 정리 완료")
        sio.emit('robot_finished', {
            'session_id': session_id
        })

@sio.event
def execute_code(data):
    global running_thread
    try:
        code = data.get('code', '')

        # 현재 세션 ID 가져오기
        session_id = data.get('session_id', '')

        # 별도 스레드에서 코드 실행
        thread = threading.Thread(
            target=exec_code,
            args=(code, session_id),
            daemon=True
        )

        # 스레드를 추적 딕셔너리에 저장
        running_thread = thread

        thread.start()

    except Exception as e:
        sio.emit('robot_stderr', {
            'session_id': session_id,
            'output': f'코드 실행 중 오류가 발생했습니다: {str(e)}'
        })

@sio.event
def stop_execution(data):
    global running_thread, stop_flag
    try:
        session_id = data.get('session_id', '')
        thread = running_thread

        if thread is None:
            sio.emit('robot_stderr', {
                'session_id': session_id,
                'output': '실행 중인 코드가 없습니다.'
            })
            return

        stop_flag = True

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

            ok = raise_in_thread(thread, SystemExit)
            thread.join(timeout=2.0)

            running_thread = None
            stop_flag = False

    except Exception as e:
        print(f"DEBUG: 스레드 중지 중 오류: {str(e)}")
        sio.emit('robot_stderr', {
            'session_id': session_id,
            'output': f'코드 중지 중 오류가 발생했습니다: {str(e)}'
        })

def heartbeat_thread():
    while True:
        if sio.connected:
            try:
                sio.emit('robot_heartbeat', {'robot_id': ROBOT_ID})
                print("하트비트 전송")
            except Exception as e:
                print(f"하트비트 전송 실패: {e}")
        time.sleep(10)

@sio.event
def client_update(data):
    import subprocess
    import os
    from pathlib import Path

    try:
        script_dir = Path(__file__).parent.absolute()
        print(f"📥 Git 업데이트 시작... (작업 디렉토리: {script_dir})")
        print(f"현재 버전: {ROBOT_VERSION}")

        # 1. 현재 ROBOT_ID와 ROBOT_NAME 저장
        print("💾 현재 로봇 설정 저장 중...")
        current_robot_id = ROBOT_ID
        current_robot_name = ROBOT_NAME
        print(f"📋 저장된 설정 - ID: {current_robot_id}, Name: {current_robot_name}")

        # 2. 로컬 변경사항을 stash로 저장
        print("💾 로컬 변경사항을 stash로 저장 중...")
        stash_result = subprocess.run(['git', 'stash', 'push', '-m', '"Auto stash before update"'],
                                    capture_output=True, text=True, cwd=str(script_dir))

        if stash_result.returncode == 0:
            print("✅ 로컬 변경사항이 stash로 저장되었습니다.")
        else:
            print(f"⚠️ Stash 저장 중 경고: {stash_result.stderr}")

        # 3. 강제로 pull 실행
        print("🔄 강제 Git pull 실행 중...")
        result = subprocess.run(['git', 'pull', 'origin', 'main'],
                              capture_output=True, text=True, cwd=str(script_dir))

        if result.returncode != 0:
            sio.emit('robot_stderr', {
                'session_id': 'system',
                'output': f"❌ Git 업데이트 실패: {result.stderr}"
            })
            return

        sio.emit('robot_stdout', {
            'session_id': 'system',
            'output': f"✅ Git 업데이트 성공: {result.stdout}"
        })

        # 4. 저장된 로봇 설정 복원
        print("🔄 저장된 로봇 설정 복원 중...")
        config_file_path = script_dir / 'robot_config.py'

        # robot_config.py 파일 읽기
        with open(config_file_path, 'r', encoding='utf-8') as f:
            config_content = f.read()

        # ROBOT_ID와 ROBOT_NAME 복원
        if current_robot_id is not None:
            # 기존 값이 있든 없든 현재 값으로 교체
            import re
            config_content = re.sub(r'ROBOT_ID\s*=\s*[^\n]+', f'ROBOT_ID = "{current_robot_id}"', config_content)
        if current_robot_name is not None:
            # 기존 값이 있든 없든 현재 값으로 교체
            import re
            config_content = re.sub(r'ROBOT_NAME\s*=\s*[^\n]+', f'ROBOT_NAME = "{current_robot_name}"', config_content)

        with open(config_file_path, 'w', encoding='utf-8') as f:
            f.write(config_content)

        print(f"✅ 로봇 설정 복원 완료 - ID: {current_robot_id}, Name: {current_robot_name}")

        # 5. 서비스 재시작
        print("🔄 서비스 재시작 중...")
        restart_result = subprocess.run(['sudo', 'systemctl', 'restart', 'robot_client.service'],
                                      capture_output=True, text=True, timeout=10)

        if restart_result.returncode == 0:
            sio.emit('robot_stdout', {
                'session_id': 'system',
                'output': "✅ 서비스 재시작 완료 - 업데이트 적용됨"
            })
        else:
            sio.emit('robot_stderr', {
                'session_id': 'system',
                'output': f"❌ 서비스 재시작 실패: {restart_result.stderr}"
            })

    except subprocess.TimeoutExpired:
        sio.emit('robot_stderr', {
            'session_id': 'system',
            'output': "❌ 업데이트/재시작 타임아웃"
        })
    except Exception as e:
        sio.emit('robot_stderr', {
            'session_id': 'system',
            'output': f"❌ 업데이트 중 오류: {str(e)}"
        })

if __name__ == "__main__":
    try:
        sio.connect(SERVER_URL)
        heartbeat_thread_obj = threading.Thread(target=heartbeat_thread, daemon=True)
        heartbeat_thread_obj.start()
        while True:
            time.sleep(1)
            if not sio.connected:
                print("Connection lost")
                sio.connect(SERVER_URL)
    except KeyboardInterrupt:
        print("KeyboardInterrupt")
        sio.disconnect()