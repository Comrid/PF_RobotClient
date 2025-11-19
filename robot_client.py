from __future__ import annotations
import subprocess
import threading
from traceback import format_exc
import socketio
import time
import asyncio
import signal
from asyncio import Queue
import cv2
import ctypes
from pathlib import Path
import sys
import json
from robot_config import ROBOT_ID, ROBOT_NAME, SERVER_URL, ROBOT_VERSION
from findee import Findee
try:
    import psutil
except ImportError:
    subprocess.run(['pip', 'install', 'psutil', '--break-system-packages'], capture_output=True, text=True)
    import psutil
try:
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, RTCDataChannel, RTCConfiguration
except ImportError:
    subprocess.run(['pip', 'install', 'aiortc', '--break-system-packages'], capture_output=True, text=True)
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, RTCDataChannel, RTCConfiguration
try:
    from packaging.version import Version
except ImportError:
    subprocess.run(['pip', 'install', 'packaging', '--break-system-packages'], capture_output=True, text=True)
    from packaging.version import Version


# 서버 연결 객체
sio = socketio.Client()
current_version = Version(ROBOT_VERSION)

#region 스레드 관리
class ThreadManager:
    def __init__(self, thread: threading.Thread):
        self.thread: threading.Thread = thread
        self.stop_flag: bool = False

session_threads: dict[str, ThreadManager] = {}
#endregion

#region ctypes 최적화
_async_exc_func = ctypes.pythonapi.PyThreadState_SetAsyncExc
_async_exc_func.argtypes = [ctypes.c_ulong, ctypes.py_object]
_async_exc_func.restype = ctypes.c_int

def _raise_exception_in_thread(thread: threading.Thread, exc_type=SystemExit) -> bool:
    if thread is None or not thread.is_alive():
        return False
    tid = ctypes.c_ulong(thread.ident)
    res = _async_exc_func(tid, ctypes.py_object(exc_type))
    if res > 1:
        _async_exc_func(tid, ctypes.py_object(0))
        return False
    return res == 1
#endregion

#region Error code
ERR__WRTC_WORKER = 0x0001
ERR__WRTC_WORKER_START = 0x0002
ERR__WRTC_OFFER = 0x0003
ERR__WRTC_OFFER_QUEUE = 0x0004
ERR__WRTC_IMAGE_IO = 0x0005
ERR__IMG_NOT_NUMPY = 0x0006
ERR__WRTC_TEXT_IO = 0x0007
ERR__WRTC_CANDIDATE_QUEUE = 0x0008
ERR__WRTC_CANDIDATE_EXTRACT = 0x0009
ERR__WRTC_CANDIDATE_HANDLE = 0x0010
#endregion

#region WebRTC 초기화
webrtc_task_queue = Queue()

class WebRTC_Manager:
    def __init__(self, connection: RTCPeerConnection):
        self.connection: RTCPeerConnection = connection
        self.data_channel: RTCDataChannel | None = None
        self.candidate_queue: list = []  # ICE candidate 큐 (setRemoteDescription 전에 도착한 candidate 저장)
        self.remote_description_set: bool = False  # Remote description 설정 완료 플래그

webrtc_loop = asyncio.new_event_loop()
webrtc_sessions: dict[str, WebRTC_Manager] = {}

# 위젯 데이터 저장소
PID_Wdata: dict[str, dict] = {}  # {"위젯이름": {"p": 1.0, "i": 0.5, "d": 0.2}}
Slider_Wdata: dict[str, list] = {}  # {"위젯이름": [10, 20, 30]}
#endregion

#region WebRTC 워커 및 초기화
async def webrtc_worker():
    asyncio.set_event_loop(webrtc_loop)

    while True:
        try:
            task_type, data = await webrtc_task_queue.get()

            if task_type == 'offer':
                session_id = data.get('session_id'); offer_dict = data.get('offer')
                if session_id and offer_dict:
                    asyncio.create_task(handle_webrtc_offer(session_id, offer_dict))

            elif task_type == 'candidate':
                session_id = data.get('session_id'); candidate_dict = data.get('candidate')
                if session_id and candidate_dict:
                    asyncio.create_task(handle_webrtc_ice_candidate(session_id, candidate_dict))

            elif task_type == 'send_image':
                session_id = data.get('session_id'); image_bytes = data.get('image_bytes'); widget_id = data.get('widget_id')
                if session_id and image_bytes and widget_id:
                    asyncio.create_task(send_image_via_webrtc(session_id, image_bytes, widget_id))

            elif task_type == 'send_text':
                session_id = data.get('session_id'); text = data.get('text'); widget_id = data.get('widget_id')
                if session_id and text and widget_id:
                    asyncio.create_task(send_text_via_webrtc_async(session_id, text, widget_id))

            elif task_type == 'send_system_info':
                session_id = data.get('session_id')
                if session_id:
                    asyncio.create_task(send_system_info_via_webrtc(session_id))

            elif task_type == 'shutdown':
                break

        except Exception:
            print(ERR__WRTC_WORKER)

def start_webrtc_loop():
    webrtc_loop.run_until_complete(webrtc_worker())
#endregion

#region WebRTC 시그널링 (연결 설정)
@sio.event
def webrtc_offer(data):
    try:
        webrtc_loop.call_soon_threadsafe(webrtc_task_queue.put_nowait, ('offer', data))
    except Exception:
        print(ERR__WRTC_OFFER_QUEUE)

async def handle_webrtc_offer(session_id, offer_dict):
    try:
        # 기존 연결이 있으면 정리
        old_session = webrtc_sessions.get(session_id)
        if old_session:
            await old_session.connection.close()
            del webrtc_sessions[session_id]

        # 새로운 피어 연결 생성
        configuration = RTCConfiguration(iceServers=[])
        pc = RTCPeerConnection(configuration=configuration)
        webrtc_sessions[session_id] = WebRTC_Manager(pc)

        # 데이터 채널 이벤트 처리
        @pc.on("datachannel")
        def on_datachannel(channel: RTCDataChannel):
            webrtc_sessions[session_id].data_channel = channel
            
            # 시스템 정보 전송 루프 시작
            async def system_info_loop():
                while session_id in webrtc_sessions:
                    session = webrtc_sessions.get(session_id)
                    if session and session.data_channel and session.data_channel.readyState == 'open':
                        try:
                            webrtc_loop.call_soon_threadsafe(
                                webrtc_task_queue.put_nowait,
                                ('send_system_info', {'session_id': session_id})
                            )
                        except Exception:
                            pass
                    await asyncio.sleep(1.0)  # 1초마다 전송
            
            asyncio.create_task(system_info_loop())

            @channel.on("message")
            def on_message(message):
                try:
                    # JSON 문자열로 전송된 위젯 데이터 파싱
                    data = json.loads(message)
                    widget_type = data.get('type')
                    widget_id = data.get('widget_id')
                    
                    if not widget_id:
                        return
                    
                    if widget_type == "pid_update":
                        PID_Wdata[widget_id] = {
                            "p": float(data.get('p', 0.0)),
                            "i": float(data.get('i', 0.0)),
                            "d": float(data.get('d', 0.0))
                        }
                    elif widget_type == "slider_update":
                        values = data.get('values', [])
                        if isinstance(values, list):
                            Slider_Wdata[widget_id] = values
                except json.JSONDecodeError:
                    # JSON이 아닌 경우 무시 (이미지/텍스트 데이터일 수 있음)
                    pass
                except Exception as e:
                    print(f"위젯 데이터 수신 오류: {e}")

        # ICE candidate 이벤트 처리
        @pc.on("icecandidate")
        def on_ice_candidate(candidate):
            if candidate:
                candidate_str = candidate.candidate
                sio.emit('webrtc_ice_candidate', {
                    'candidate': {
                        'candidate': candidate_str,
                        'sdpMLineIndex': candidate.sdpMLineIndex,
                        'sdpMid': candidate.sdpMid
                    },
                    'session_id': session_id
                })
            else:
                sio.emit('webrtc_ice_candidate', {
                    'candidate': None,
                    'session_id': session_id
                })

        # 연결 상태 변경 모니터링
        @pc.on("connectionstatechange")
        def on_connection_state_change():
            if pc.connectionState == "failed" or pc.connectionState == "closed":
                # 연결 실패 시 정리
                if session_id in webrtc_sessions:
                    del webrtc_sessions[session_id]

        # ICE 수집 상태 변경 모니터링
        @pc.on("icegatheringstatechange")
        def on_ice_gathering_state_change():
            if pc.iceGatheringState == "complete" and pc.localDescription:
                extract_and_send_candidates_from_sdp(pc.localDescription.sdp, session_id)

        # Offer 설정
        offer = RTCSessionDescription(sdp=offer_dict['sdp'], type=offer_dict['type'])
        await pc.setRemoteDescription(offer)

        # Remote description 설정 완료 플래그 설정
        session = webrtc_sessions[session_id]
        session.remote_description_set = True

        # 큐에 저장된 ICE candidate 처리
        if session.candidate_queue:
            for candidate_dict in session.candidate_queue:
                try:
                    candidate_str = candidate_dict.get('candidate', '')
                    if candidate_str:
                        candidate = create_ice_candidate(
                            candidate_str,
                            sdp_mid=candidate_dict.get('sdpMid'),
                            sdp_m_line_index=candidate_dict.get('sdpMLineIndex')
                        )
                        if candidate:
                            await pc.addIceCandidate(candidate)
                except Exception:
                    pass
            session.candidate_queue = []  # 큐 비우기

        # Answer 생성
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        # Answer 전송
        sio.emit('webrtc_answer', {'answer': {'type': pc.localDescription.type, 'sdp': pc.localDescription.sdp}, 'session_id': session_id})
    except Exception:
        print(ERR__WRTC_OFFER)

@sio.event
def webrtc_ice_candidate(data):
    try:
        webrtc_loop.call_soon_threadsafe(webrtc_task_queue.put_nowait, ('candidate', data))
    except Exception:
        print(ERR__WRTC_CANDIDATE_QUEUE)

async def handle_webrtc_ice_candidate(session_id, candidate_dict):
    try:
        session = webrtc_sessions.get(session_id)
        if not session:
            return

        candidate_str = candidate_dict.get('candidate', '')
        if not candidate_str:
            return

        # Remote description 체크
        if not session.remote_description_set:
            # 큐에 저장
            session.candidate_queue.append(candidate_dict)
            return

        # Remote description이 설정되었으면 바로 추가
        try:
            candidate = create_ice_candidate(
                candidate_str,
                sdp_mid=candidate_dict.get('sdpMid'),
                sdp_m_line_index=candidate_dict.get('sdpMLineIndex')
            )
            if candidate:
                await session.connection.addIceCandidate(candidate)
        except Exception:
            pass  # 일부 candidate 실패는 정상

    except Exception:
        print(ERR__WRTC_CANDIDATE_HANDLE)
#endregion

#region WebRTC ICE Candidate 처리
def extract_and_send_candidates_from_sdp(sdp: str, session_id: str):
    """SDP에서 ICE candidate를 추출하여 브라우저로 전송 (aiortc는 Trickle ICE 미지원)"""
    try:
        # SDP에서 candidate 라인 찾기 (a=candidate: 제거하면서 바로 추출)
        candidate_lines = [line[2:] for line in sdp.split('\n') if line.startswith('a=candidate:')]

        if not candidate_lines:
            return

        # 각 candidate 전송 (파싱 없이 그대로 전송)
        for candidate_str in candidate_lines:
            try:
                # 최소 길이 검증만 (파싱 불필요 - 브라우저에서 파싱함)
                if len(candidate_str) < 20:
                    continue

                sio.emit('webrtc_ice_candidate', {
                    'candidate': {'candidate': candidate_str, 'sdpMLineIndex': 0, 'sdpMid': '0'},
                    'session_id': session_id
                })
            except Exception:
                pass  # 개별 candidate 실패는 무시

        # candidate 수집 완료 신호 전송
        sio.emit('webrtc_ice_candidate', {'candidate': None, 'session_id': session_id})
    except Exception:
        print(ERR__WRTC_CANDIDATE_EXTRACT)

def create_ice_candidate(candidate_str, sdp_mid=None, sdp_m_line_index=None):
    """SDP candidate 문자열을 파싱하여 RTCIceCandidate 객체 생성"""
    try:
        if not candidate_str or not isinstance(candidate_str, str):
            return None

        # candidate: 접두사 제거
        if candidate_str.startswith('candidate:'): candidate_str = candidate_str[10:]
        parts = candidate_str.strip().split()
        if len(parts) < 8:
            return None

        foundation = parts[0]
        component = int(parts[1])
        protocol = parts[2].upper()
        priority = int(parts[3])
        ip = parts[4]
        port = int(parts[5])

        # 한 번의 루프로 typ, raddr, rport 찾기
        typ = 'host'  # 기본값
        related_address = None
        related_port = None

        for i, part in enumerate(parts):
            if part == 'typ' and i + 1 < len(parts):
                typ = parts[i + 1]
            elif part == 'raddr' and i + 1 < len(parts):
                related_address = parts[i + 1]
            elif part == 'rport' and i + 1 < len(parts):
                related_port = int(parts[i + 1])

        return RTCIceCandidate(
            foundation=foundation,
            component=component,
            protocol=protocol,
            priority=priority,
            ip=ip,
            port=port,
            type=typ,
            relatedAddress=related_address,
            relatedPort=related_port,
            sdpMid=sdp_mid,
            sdpMLineIndex=sdp_m_line_index
        )
    except Exception:
        return None
#endregion

#region WebRTC 데이터 전송
# WebRTC 데이터 채널을 통해 데이터 전송 (비동기, 바이너리 프로토콜)
async def send_image_via_webrtc(session_id, image_bytes, widget_id):
    try:
        session = webrtc_sessions.get(session_id)
        if not session:
            return

        data_channel = session.data_channel
        if not data_channel or data_channel.readyState != 'open':
            return

        # 바이너리 프로토콜: [타입(1)][widget_id 길이(1)][widget_id(가변)][이미지 데이터(가변)]
        # 타입: 0x01 = image
        widget_id_bytes = widget_id.encode('utf-8')
        widget_id_len = len(widget_id_bytes)

        header = bytes([0x01, widget_id_len]) + widget_id_bytes
        data_channel.send(header + image_bytes)
    except Exception:
        pass

async def send_text_via_webrtc_async(session_id, text, widget_id):
    try:
        session = webrtc_sessions.get(session_id)
        if not session:
            return

        data_channel = session.data_channel
        if not data_channel or data_channel.readyState != 'open':
            return

        # 바이너리 프로토콜: [타입(1)][widget_id 길이(1)][widget_id(가변)][텍스트 데이터(가변)]
        # 타입: 0x02 = text
        widget_id_bytes = widget_id.encode('utf-8')
        widget_id_len = len(widget_id_bytes)
        text_bytes = text.encode('utf-8')

        header = bytes([0x02, widget_id_len]) + widget_id_bytes
        data_channel.send(header + text_bytes)

    except Exception:
        pass

async def send_system_info_via_webrtc(session_id):
    """시스템 정보를 WebRTC DataChannel로 전송"""
    try:
        session = webrtc_sessions.get(session_id)
        if not session:
            return

        data_channel = session.data_channel
        if not data_channel or data_channel.readyState != 'open':
            return

        # 시스템 정보 수집
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        ram_percent = memory.percent
        ram_used = memory.used / (1024**3)  # GB
        ram_total = memory.total / (1024**3)  # GB
        
        # 온도 정보 (라즈베리파이)
        temp = None
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp_raw = int(f.read().strip())
                temp = temp_raw / 1000.0  # 섭씨
        except:
            pass

        # JSON 형식으로 전송
        system_info = {
            'type': 'system_info',
            'cpu_percent': round(cpu_percent, 1),
            'ram_percent': round(ram_percent, 1),
            'ram_used': round(ram_used, 2),
            'ram_total': round(ram_total, 2),
            'temp': round(temp, 1) if temp else None
        }
        
        data_channel.send(json.dumps(system_info))
    except Exception:
        pass
#endregion

#region SocketIO 이벤트 핸들러 (서버 연결)
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

@sio.event
def disconnect():
    def reconnect_loop():
        while not sio.connected:
            try:
                threading.Timer(5.0, lambda: sio.connect(SERVER_URL)).start()
            except Exception:
                pass
    threading.Thread(target=reconnect_loop, daemon=True).start()
#endregion

#region 위젯 데이터 접근 함수
def get_pid(widget_id: str) -> tuple[float | None, float | None, float | None]:
    """PID 위젯 데이터 가져오기"""
    data = PID_Wdata.get(widget_id)
    if data:
        return data['p'], data['i'], data['d']
    return None, None, None

def get_slider(widget_id: str) -> list:
    """Slider 위젯 데이터 가져오기 (항상 배열)"""
    return Slider_Wdata.get(widget_id, [])
#endregion

#region 코드 실행
def exec_code(code, session_id):
    if session_id in session_threads:
        session_threads[session_id].stop_flag = False

    def check_stop_flag(func):
        def wrapper(*args, **kwargs):
            if session_id in session_threads and session_threads[session_id].stop_flag:
                return
            return func(*args, **kwargs)
        return wrapper

    @check_stop_flag
    def realtime_print(*args, **kwargs):
        output = ' '.join(str(arg) for arg in args)
        if output: sio.emit('robot_stdout', {'session_id': session_id, 'output': output})

    try:
        #TODO 프레임 스킵
        @check_stop_flag
        def emit_image(image, widget_id):
            if not hasattr(image, 'shape'):
                print(ERR__IMG_NOT_NUMPY)
                raise Exception("ERR__IMG_NOT_NUMPY")

            ok, buffer = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
            if not ok: return
            image_bytes = buffer.tobytes()

            session = webrtc_sessions.get(session_id)
            data_channel = session.data_channel if session else None
            if data_channel and data_channel.readyState == 'open':
                try:
                    webrtc_loop.call_soon_threadsafe(
                        webrtc_task_queue.put_nowait,
                        ('send_image', {'session_id': session_id, 'image_bytes': image_bytes, 'widget_id': widget_id})
                    )
                    return
                except Exception:
                    print(ERR__WRTC_IMAGE_IO)
                    sio.emit('robot_emit_image', {'session_id': session_id, 'image_data': image_bytes, 'widget_id': widget_id})

        @check_stop_flag
        def emit_text(text, widget_id):
            session = webrtc_sessions.get(session_id)
            data_channel = session.data_channel if session else None
            if data_channel and data_channel.readyState == 'open':
                try:
                    webrtc_loop.call_soon_threadsafe(
                        webrtc_task_queue.put_nowait,
                        ('send_text', {'session_id': session_id, 'text': text, 'widget_id': widget_id})
                    )
                    return
                except Exception:
                    print(ERR__WRTC_TEXT_IO)
                    sio.emit('robot_emit_text', {'session_id': session_id, 'text': text, 'widget_id': widget_id})

        exec_namespace = {
            'Findee': Findee,
            'emit_image': emit_image,
            'emit_text': emit_text,
            'print': realtime_print,
            'get_pid': get_pid,
            'get_slider': get_slider
        }
        compiled_code = compile(code, '<string>', 'exec')
        exec(compiled_code, exec_namespace)
    except Exception:
        for line in format_exc().splitlines():
            sio.emit('robot_stderr', {'session_id': session_id, 'output': line})
    finally:
        # 세션별 정리
        if session_id in session_threads:
            del session_threads[session_id]
        sio.emit('robot_finished', {'session_id': session_id})
        Findee().stop()

@sio.event
def execute_code(data):
    try:
        code = data.get('code', '')
        session_id = data.get('session_id', '')

        # 기존 실행 중인 스레드가 있으면 먼저 정리
        if session_id in session_threads:
            old_manager = session_threads[session_id]
            if old_manager.thread.is_alive():
                old_manager.stop_flag = True
                _raise_exception_in_thread(old_manager.thread, SystemExit)
                old_manager.thread.join(timeout=0.5)

        # 새 스레드 시작
        thread = threading.Thread(target=exec_code, args=(code, session_id), daemon=True)
        session_threads[session_id] = ThreadManager(thread)
        thread.start()
    except Exception as e:
        sio.emit('robot_stderr', {'session_id': session_id, 'output': f'코드 실행 중 오류: {str(e)}'})

@sio.event
def stop_execution(data):
    try:
        session_id = data.get('session_id', '')

        if session_id not in session_threads:
            sio.emit('robot_stderr', {'session_id': session_id, 'output': '실행 중인 코드가 없습니다.'})
            return

        manager = session_threads[session_id]
        manager.stop_flag = True

        if manager.thread.is_alive():
            _raise_exception_in_thread(manager.thread, SystemExit)
            manager.thread.join(timeout=1.0)

        # 세션별 정리
        if session_id in session_threads:
            del session_threads[session_id]
    except Exception as e:
        sio.emit('robot_stderr', {'session_id': session_id, 'output': f'코드 중지 중 오류: {str(e)}'})

@sio.event
def pid_update(data):
    """PID 업데이트 데이터 수신 (SocketIO fallback)"""
    try:
        widget_id = data.get('widget_id')
        if widget_id:
            PID_Wdata[widget_id] = {
                "p": float(data.get('p', 0.0)),
                "i": float(data.get('i', 0.0)),
                "d": float(data.get('d', 0.0))
            }
    except Exception as e:
        print(f"PID 업데이트 수신 오류: {e}")

@sio.event
def slider_update(data):
    """Slider 업데이트 데이터 수신 (SocketIO fallback)"""
    try:
        widget_id = data.get('widget_id')
        values = data.get('values', [])
        if widget_id and isinstance(values, list):
            Slider_Wdata[widget_id] = values
    except Exception as e:
        print(f"Slider 업데이트 수신 오류: {e}")
#endregion

#region 로봇 업데이트/초기화
def force_git_pull(ScriptDir):
    # 로컬 변경사항을 stash로 저장 및 Git pull 실행
    subprocess.run(['git', 'stash', 'push', '-m', '"Temp"'], capture_output=True, text=True, cwd=str(ScriptDir))
    subprocess.run(['git', 'pull', 'origin', 'main'], capture_output=True, text=True, cwd=str(ScriptDir))

@sio.event
def client_update(data):
    try:
        ScriptDir = Path(__file__).parent.absolute() # 현재 파일의 디렉토리
        RobotID, RobotName = ROBOT_ID, ROBOT_NAME # 현재 로봇 설정 저장
        force_git_pull(ScriptDir) # 강제 Git pull
        # 로봇 설정 복원
        subprocess.run(f"sed -i 's/ROBOT_ID = .*/ROBOT_ID = \"{RobotID}\"/' {ScriptDir}/robot_config.py", shell=True, check=True)
        subprocess.run(f"sed -i 's/ROBOT_NAME = .*/ROBOT_NAME = \"{RobotName}\"/' {ScriptDir}/robot_config.py", shell=True, check=True)
        # 서비스 재시작
        subprocess.run(['sudo', 'systemctl', 'restart', 'robot_client.service'], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass

@sio.event
def client_reset(data):
    subprocess.run("echo 'MODE=AP' | sudo tee /etc/pf_env", shell=True, check=True) # /etc/pf_env 파일 수정
    ScriptDir = Path(__file__).parent.absolute() # 현재 파일의 디렉토리
    force_git_pull(ScriptDir)
    subprocess.Popen(["sudo", "reboot"]) # 재부팅
#endregion

#region Signal handler
def signal_handler(signum, frame):
    if webrtc_sessions:
        try:
            async def cleanup_async():
                tasks = [session.connection.close() for session in webrtc_sessions.values()]
                await asyncio.gather(*tasks, return_exceptions=True)
                webrtc_sessions.clear()
            if webrtc_loop and webrtc_loop.is_running():
                webrtc_loop.run_until_complete(cleanup_async())
            else:
                asyncio.run(cleanup_async())
        except Exception:
            pass
    sio.disconnect()
    sys.exit(0)
#endregion

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    webrtc_thread = threading.Thread(target=start_webrtc_loop, daemon=True)
    webrtc_thread.start()
    sio.connect(SERVER_URL)
    while True:
        time.sleep(5)
