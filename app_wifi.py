# 라즈베리파이 제로 2에 AP 연결시 나오는 개인 전용 웹 사이트
# 사용자가 연결할 와이파이, 비밀번호를 입력하면 와이파이 정보를 wpa_supplicant.conf에 저장하고 재설정
# 로봇 이름은 랜덤 ID를 부여하고 robot_config.py에 저장(단, 이름 중복 문제가 있음. 나중에 개선 필요)
# 이후 로봇 클라이언트가 이 파일을 읽어서 와이파이 정보와 로봇 이름을 사용
# 클라이언트 모드로 변경

from flask import Flask, render_template, request, jsonify, redirect, url_for
import subprocess
import re
import uuid
import os
import platform
import time

from robot_config import ROBOT_NAME_DEFAULT
SERVER_URL = "https://pathfinder-kit.duckdns.org"
DISPLAY_MESSAGE = None # 정상 메시지 또는 오류 메시지

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/robot-name')
def get_robot_name():
    try:
        return jsonify({
            "success": True,
            "robot_name": ROBOT_NAME_DEFAULT
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/display_message')
def get_display_message():
    return jsonify({"success": True, "message": DISPLAY_MESSAGE})

def update_robot_config(robot_id):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, "robot_config.py")

    with open(config_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    updated_lines = []
    for line in lines:
        if line.startswith('ROBOT_ID ='):
            updated_lines.append(f'ROBOT_ID = "{robot_id}"\n')
        elif line.startswith('ROBOT_NAME ='):
            updated_lines.append(f'ROBOT_NAME = "{ROBOT_NAME_DEFAULT}"\n')
        else:
            updated_lines.append(line)

    with open(config_path, 'w') as f:
        f.writelines(updated_lines)

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

def restore_ap_mode():
    """AP 모드로 복귀"""
    try:
        subprocess.run(["sudo", "nmcli", "con", "up", "Pathfinder-AP"],
                      capture_output=True, timeout=10)
    except:
        pass

@app.route('/connect', methods=['POST'])
def setup_robot():
    global DISPLAY_MESSAGE
    try:
        data = request.get_json()
        ssid = data.get('ssid')
        password = data.get('password')

        # 기본 검증
        if not all([ssid, password]):
            return jsonify({"success": False, "error": "SSID, 비밀번호를 모두 입력해주세요."}), 400
        if not (8 <= len(password) <= 63):
            return jsonify({"success": False, "error": "WiFi 비밀번호는 8자 이상, 63자 이하여야 합니다."}), 400

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
            modify_command = [
                "sudo", "nmcli", "connection", "modify", PROFILE_NAME,
                "wifi-sec.key-mgmt", "wpa-psk",
                "wifi-sec.psk", password,
                "connection.autoconnect", "yes"
            ]
            subprocess.run(modify_command, check=True, text=True, capture_output=True, timeout=15)

            # 로봇 설정 업데이트
            robot_id = f"robot_{uuid.uuid4().hex[:8]}"
            update_robot_config(robot_id)

            # /etc/pf_env 파일 수정
            subprocess.run("echo 'MODE=CLIENT' | sudo tee /etc/pf_env", shell=True, check=True)

            # 모드 전환 스크립트 실행(백그라운드)
            subprocess.Popen(["sudo", "/usr/local/bin/pf-netmode-bookworm.sh"])

            return jsonify({
                "success": True,
                "message": "WiFi 정보 저장 성공! 클라이언트 모드로 전환합니다.",
                "robot_name": ROBOT_NAME_DEFAULT,
                "robot_id": robot_id
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e) + "(WIFI SETUP ERROR)"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e) + "(API ERROR)"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)