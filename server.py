from flask import Flask, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room
import os
import uuid
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'  # 替换为安全的密钥
socketio = SocketIO(app)

# 配置
PHOTO_DIR = 'photos'
CLIENT_ROOM = 'clients'
SERVER_HOST = '0.0.0.0'
SERVER_PORT = 5000

# 确保照片目录存在
os.makedirs(PHOTO_DIR, exist_ok=True)

# 客户端状态管理
clients = {}

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/photos')
def get_photos():
    """获取照片列表"""
    photos = []
    for filename in os.listdir(PHOTO_DIR):
        if filename.endswith('.jpg') or filename.endswith('.png'):
            file_path = os.path.join(PHOTO_DIR, filename)
            photos.append({
                'filename': filename,
                'size': os.path.getsize(file_path),
                'timestamp': os.path.getmtime(file_path)
            })
    # 按时间倒序排序
    photos.sort(key=lambda x: x['timestamp'], reverse=True)
    return jsonify(photos)

@app.route('/photos/<filename>')
def get_photo(filename):
    """下载照片"""
    # 确保文件名安全，防止路径遍历攻击
    if '..' in filename or '/' in filename:
        return jsonify({'error': 'Invalid filename'}), 400
    
    # 确保文件存在且在正确目录中
    file_path = os.path.join(PHOTO_DIR, filename)
    if not os.path.isfile(file_path):
        return jsonify({'error': 'File not found'}), 404
    
    return send_from_directory(PHOTO_DIR, filename, as_attachment=True)

@app.route('/upload', methods=['POST'])
def upload_photo():
    """接收客户端上传的照片"""
    if 'photo' not in request.files:
        return jsonify({'error': 'No photo file'}), 400
    
    file = request.files['photo']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    # 生成唯一文件名
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique_id = str(uuid.uuid4())[:8]
    filename = f"{timestamp}_{unique_id}.jpg"
    file_path = os.path.join(PHOTO_DIR, filename)
    
    file.save(file_path)
    return jsonify({'success': True, 'filename': filename})

@app.route('/shoot', methods=['POST'])
def shoot():
    """接收网页拍摄指令，转发给客户端"""
    # 记录拍摄指令请求
    print(f"Shoot command received, broadcasting to {len(clients)} clients")
    
    # 直接向所有客户端发送shoot事件，确保指令传递
    for client_id in clients:
        socketio.emit('shoot', room=client_id)
        print(f"Sent shoot command to client: {client_id}")
    
    return jsonify({'success': True, 'message': f'Shoot command sent to {len(clients)} clients'})

@app.route('/clients')
def get_clients():
    """获取客户端列表"""
    return jsonify(list(clients.keys()))

@socketio.on('connect')
def handle_connect():
    """处理客户端连接"""
    client_id = request.sid
    
    # 从请求头判断是否为摄像头客户端（摄像头客户端会发送特殊标识）
    user_agent = request.headers.get('User-Agent', '')
    # 只有包含'CameraClient'标识的连接才被视为摄像头客户端
    if 'CameraClient' in user_agent:
        clients[client_id] = {
            'connected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        join_room(CLIENT_ROOM)
        print(f"Camera client connected: {client_id}")
        emit('client_connected', {'client_id': client_id}, broadcast=True)
    else:
        print(f"Web client connected: {client_id}")

@socketio.on('disconnect')
def handle_disconnect():
    """处理客户端断开连接"""
    client_id = request.sid
    if client_id in clients:
        del clients[client_id]
        print(f"Camera client disconnected: {client_id}")
        emit('client_disconnected', {'client_id': client_id}, broadcast=True)
    else:
        print(f"Web client disconnected: {client_id}")

if __name__ == '__main__':
    print(f"Server starting on {SERVER_HOST}:{SERVER_PORT}")
    print(f"Photos will be stored in: {os.path.abspath(PHOTO_DIR)}")
    socketio.run(app, host=SERVER_HOST, port=SERVER_PORT, debug=False)