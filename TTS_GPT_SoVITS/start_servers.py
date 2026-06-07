"""
启动TTS WebSocket服务器和HTTP文件服务器
"""
import subprocess
import sys
import time
import socket


def start_http_server():
    return subprocess.Popen([sys.executable, "http_file_server.py",
        "--host", "localhost", "--port", "8005"])

def start_websocket_server():
    return subprocess.Popen([sys.executable, "tts_websocket_server.py",
        "--host", "localhost", "--port", "8770"])

def wait_for_port(host, port, timeout=180):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    return False

def main():
    print("TTS服务启动中...", flush=True)
    try:
        http_process = start_http_server()
        time.sleep(1)
        ws_process = start_websocket_server()
        if wait_for_port("localhost", 8770, timeout=180):
            print("TTS服务器就绪", flush=True)
        else:
            print("TTS服务器启动超时", flush=True)
            ws_process.terminate()
            http_process.terminate()
            sys.exit(1)
        http_process.wait()
        ws_process.wait()
    except KeyboardInterrupt:
        http_process.terminate()
        ws_process.terminate()
        http_process.wait()
        ws_process.wait()
    except Exception as e:
        print(f"启动失败: {e}", flush=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
