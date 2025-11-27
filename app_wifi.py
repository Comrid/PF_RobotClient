# 라즈베리파이 제로 2에 AP 연결시 나오는 개인 전용 웹 사이트
# 사용자가 연결할 와이파이, 비밀번호를 입력하면 와이파이 정보를 wpa_supplicant.conf에 저장하고 재설정
# 로봇 이름은 랜덤 ID를 부여하고 robot_config.py에 저장(단, 이름 중복 문제가 있음. 나중에 개선 필요)
# 이후 로봇 클라이언트가 이 파일을 읽어서 와이파이 정보와 로봇 이름을 사용
# 클라이언트 모드로 변경
from pathlib import Path
from flask import Flask, render_template, request, jsonify, redirect, url_for
import subprocess
import platform
import time

def get_default_robot_name():
    # /etc/pf_default_robot_name에서 로봇 이름 읽기
    result = subprocess.run(["cat", "/etc/pf_default_robot_name"], capture_output=True, text=True, check=True)
    return result.stdout.strip()

def get_robot_id():
    # /etc/pf_id에서 로봇 ID 읽기
    result = subprocess.run(["cat", "/etc/pf_id"], capture_output=True, text=True, check=True)
    return result.stdout.strip()

def restore_ap_mode():
    subprocess.run(["sudo", "nmcli", "con", "up", "Pathfinder-AP"], capture_output=True, timeout=10)


app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/robot-name')
def get_robot_name():
    return jsonify({"success": True, "robot_name": get_default_robot_name()})

@app.route("/generate_204")
@app.route("/gen_204")
@app.route("/hotspot-detect.html")
@app.route("/library/test/success.html")
@app.route("/success.txt")
@app.route("/connecttest.txt")
@app.route("/redirect")
@app.route("/ncsi.txt")
def captive_probe_redirect():
    return redirect(url_for("index"), code=302)

@app.route('/connect', methods=['POST'])
def connect():
    try:
        data = request.get_json()
        ssid = data.get('ssid')
        password = data.get('password')

        # 기본 검증
        if not ssid:
            return jsonify({"success": False, "error": "SSID를 입력해주세요."}), 400
        # 비밀번호가 있는 경우에만 길이 검증
        if password and not (8 <= len(password) <= 63):
            return jsonify({"success": False, "error": "WiFi 비밀번호는 8자 이상, 63자 이하여야 합니다."}), 400

        if platform.system() == "Linux":
            try:
                # 동일한 이름의 프로필이 있다면 삭제
                PROFILE_NAME = "Pathfinder-Client"
                subprocess.run(["sudo", "nmcli", "connection", "delete", PROFILE_NAME], capture_output=True)

                # 새로운 프로필 추가
                add_command = [
                    "sudo", "nmcli", "connection", "add",
                    "type", "wifi",
                    "con-name", PROFILE_NAME,
                    "ifname", "wlan0",
                    "ssid", ssid
                ]
                subprocess.run(add_command, check=True, text=True, capture_output=True, timeout=15)

                # 생성된 프로필에 비밀번호와 자동 연결 설정
                if password and password.strip():
                    # 비밀번호가 있는 경우: WPA-PSK 사용
                    modify_command = [
                        "sudo", "nmcli", "connection", "modify", PROFILE_NAME,
                        "wifi-sec.key-mgmt", "wpa-psk",
                        "wifi-sec.psk", password,
                        "connection.autoconnect", "yes"
                    ]
                else:
                    # 비밀번호가 없는 경우: 오픈 네트워크 (key-mgmt: none)
                    modify_command = [
                        "sudo", "nmcli", "connection", "modify", PROFILE_NAME,
                        "wifi-sec.key-mgmt", "none",
                        "connection.autoconnect", "yes"
                    ]
                subprocess.run(modify_command, check=True, text=True, capture_output=True, timeout=15)

                # 로봇 설정 업데이트
                ScriptDir = Path(__file__).parent.absolute() # 현재 파일의 디렉토리
                robot_id = get_robot_id()
                subprocess.run(f"sed -i 's/ROBOT_ID = .*/ROBOT_ID = \"{robot_id}\"/' {ScriptDir}/robot_config.py", shell=True, check=True)
                subprocess.run(f"sed -i 's/ROBOT_NAME = .*/ROBOT_NAME = \"{get_default_robot_name()}\"/' {ScriptDir}/robot_config.py", shell=True, check=True)

                # /etc/pf_env 파일 수정
                subprocess.run("echo 'MODE=CLIENT' | sudo tee /etc/pf_env", shell=True, check=True)

                return jsonify({
                    "success": True,
                    "message": "WiFi 정보 저장 성공! 클라이언트 모드로 전환합니다.",
                    "robot_name": get_default_robot_name()
                })
            except Exception as e:
                return jsonify({"success": False, "error": str(e) + "(WIFI SETUP ERROR)"}), 500
            finally:
                # 모드 전환 스크립트 실행(백그라운드)
                subprocess.Popen(["sudo", "/usr/local/bin/pf-netmode-bookworm.sh"])
        else:
            time.sleep(2)
            return jsonify({"success": True, "robot_name": "Testbot", "message": "Linux 환경이 아닙니다."})

    except Exception as e:
        return jsonify({"success": False, "error": str(e) + "(API ERROR)"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

