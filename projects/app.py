"""
Link2Reels - Flask Application

Shopify 产品链接 → 自动生成短视频系统
支持两步流程：先抓取预览，再生成视频
"""

import os
import sys
import uuid
import logging
import json
import base64
import hashlib
import time
from pathlib import Path
from functools import wraps
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, send_file, render_template, Response, make_response
from flask_cors import CORS

# 添加 app 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app'))

from scraper import ProductScraper
from image_processor import ImageDownloader
from video_generator import VideoGenerator
from task_queue import TaskQueue, task_queue, TaskStatus

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建 Flask 应用
app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

# 配置
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['TEMP_DIR'] = os.environ.get('TEMP_DIR', '/tmp/link2reels')
app.config['OUTPUT_DIR'] = os.environ.get('OUTPUT_DIR', '/tmp/link2reels/output')
app.config['UPLOAD_DIR'] = os.environ.get('UPLOAD_DIR', '/tmp/link2reels/uploads')

# 确保目录存在
for dir_path in [app.config['TEMP_DIR'], app.config['OUTPUT_DIR'], app.config['UPLOAD_DIR']]:
    os.makedirs(dir_path, exist_ok=True)

# ============ 登录认证配置 ============
# 已暂停：设为 False 可临时禁用登录
AUTH_ENABLED = os.environ.get('AUTH_ENABLED', 'false').lower() == 'true'
AUTH_PASSWORD = os.environ.get('AUTH_PASSWORD', 'C')
AUTH_COOKIE_NAME = 'link2reels_auth'
AUTH_COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7天

def generate_token():
    """生成认证 Token"""
    return hashlib.sha256(f"{time.time()}{AUTH_PASSWORD}".encode()).hexdigest()[:32]

def check_auth():
    """检查是否已登录"""
    if not AUTH_ENABLED:
        return True
    token = request.cookies.get(AUTH_COOKIE_NAME)
    return token == AUTH_PASSWORD  # 简化：token 即密码

def require_auth(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not check_auth():
            return jsonify({'success': False, 'error': '未登录', 'need_login': True}), 401
        return f(*args, **kwargs)
    return decorated


def cleanup_old_files(max_tasks=10):
    """清理旧任务，只保留最近生成的max_tasks个"""
    try:
        output_dir = app.config['OUTPUT_DIR']
        
        # 获取所有任务目录（按修改时间排序）
        task_dirs = []
        for task_id in os.listdir(output_dir):
            task_path = os.path.join(output_dir, task_id)
            if os.path.isdir(task_path):
                # 获取最后修改时间
                mtime = os.path.getmtime(task_path)
                task_dirs.append((mtime, task_id, task_path))
        
        # 按时间排序（最新的在前）
        task_dirs.sort(reverse=True)
        
        # 删除超出数量的旧任务
        if len(task_dirs) > max_tasks:
            for _, task_id, task_path in task_dirs[max_tasks:]:
                try:
                    import shutil
                    shutil.rmtree(task_path)
                    logger.info(f"已清理旧任务: {task_id}")
                except Exception as e:
                    logger.warning(f"清理任务失败 {task_id}: {e}")
        
        # 清理临时目录（session 目录）
        temp_dir = app.config['TEMP_DIR']
        if os.path.exists(temp_dir):
            session_dirs = []
            for session_id in os.listdir(temp_dir):
                session_path = os.path.join(temp_dir, session_id)
                if os.path.isdir(session_path):
                    mtime = os.path.getmtime(session_path)
                    session_dirs.append((mtime, session_id, session_path))
            
            # 按时间排序
            session_dirs.sort(reverse=True)
            
            # 只保留最近50个临时目录
            if len(session_dirs) > 50:
                for _, session_id, session_path in session_dirs[50:]:
                    try:
                        import shutil
                        shutil.rmtree(session_path)
                        logger.info(f"已清理旧会话: {session_id}")
                    except Exception as e:
                        logger.warning(f"清理会话失败 {session_id}: {e}")
    except Exception as e:
        logger.warning(f"清理旧文件失败: {e}")


class VideoGenerationError(Exception):
    """视频生成错误"""
    pass


# ============ 登录认证接口 ============

@app.route('/api/auth/login', methods=['POST'])
def login():
    """登录"""
    data = request.get_json() or {}
    password = data.get('password', '')
    
    if password == AUTH_PASSWORD:
        response = make_response(jsonify({'success': True, 'message': '登录成功'}))
        response.set_cookie(AUTH_COOKIE_NAME, AUTH_PASSWORD, max_age=AUTH_COOKIE_MAX_AGE)
        logger.info("登录成功")
        return response
    
    logger.warning(f"登录失败: 密码错误")
    return jsonify({'success': False, 'error': '密码错误'}), 401


@app.route('/api/auth/check')
def check_login():
    """检查登录状态"""
    return jsonify({'success': True, 'logged_in': check_auth()})


@app.route('/')
def index():
    """首页"""
    if not check_auth():
        return render_template('login.html')
    return render_template('index.html')


@app.route('/api/session/create', methods=['POST'])
@require_auth
def create_session():
    """
    创建任务会话
    抓取产品信息并保存到会话中

    请求体:
    {
        "url": "https://example.myshopify.com/products/xxx"
    }

    响应:
    {
        "success": true,
        "session_id": "xxx",
        "data": {
            "title": "产品标题",
            "price": "$99.00",
            "images": [
                {"id": "1", "url": "...", "thumbnail_url": "..."},
                ...
            ]
        }
    }
    """
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'success': False, 'error': '缺少 URL 参数'}), 400

        url = data['url'].strip()
        if not url:
            return jsonify({'success': False, 'error': 'URL 不能为空'}), 400

        logger.info(f"创建会话，抓取产品: {url}")

        # 抓取产品信息
        scraper = ProductScraper()
        product_data = scraper.scrape(url)

        # 生成会话 ID
        session_id = str(uuid.uuid4())[:12]
        session_dir = os.path.join(app.config['TEMP_DIR'], session_id)
        os.makedirs(session_dir, exist_ok=True)

        # 保存会话数据
        session_data = {
            'session_id': session_id,
            'url': url,
            'title': product_data.get('title', ''),
            'price': product_data.get('price', ''),
            'original_url': product_data.get('original_url', url),
            'images': [
                {'id': str(uuid.uuid4())[:8], 'url': img_url, 'order': i}
                for i, img_url in enumerate(product_data.get('images', []))
            ],
            'custom_images': [],  # 用户上传的图片
            'created_at': datetime.now().isoformat()
        }

        # 下载原始图片作为预览
        processor = ImageDownloader(max_images=8)
        preview_images = []

        for i, img_info in enumerate(session_data['images']):
            img_url = img_info['url']
            img_info['original_url'] = img_url  # 保存原始 URL 作为备用

            try:
                logger.info(f"下载预览图 {i+1}: {img_url[:100]}...")
                img_data = processor.processor.download_and_validate(img_url)

                if img_data:
                    preview_path = os.path.join(session_dir, f'preview_{i + 1}.jpg')
                    from PIL import Image
                    import io

                    img = Image.open(io.BytesIO(img_data))

                    # 处理透明通道
                    if img.mode in ('RGBA', 'LA', 'P'):
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        if img.mode == 'RGBA':
                            background.paste(img, mask=img.split()[-1])
                        else:
                            background.paste(img)
                        img = background
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')

                    # Contain 缩放（完整显示，填充背景）
                    target_w, target_h = 400, 500
                    bg_color = (240, 240, 240)  # 浅灰色填充
                    
                    # 计算缩放比例（完整显示，不裁剪）
                    scale = min(target_w / img.width, target_h / img.height)
                    new_width = int(img.width * scale)
                    new_height = int(img.height * scale)
                    
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    
                    # 创建画布并居中放置
                    canvas = Image.new('RGB', (target_w, target_h), bg_color)
                    x_offset = (target_w - new_width) // 2
                    y_offset = (target_h - new_height) // 2
                    canvas.paste(img, (x_offset, y_offset))
                    
                    canvas.save(preview_path, 'JPEG', quality=85)

                    img_info['thumbnail_url'] = f'/session-preview/{session_id}/{i + 1}.jpg'
                    preview_images.append(img_info)
                    logger.info(f"预览图保存成功: preview_{i + 1}.jpg")
                else:
                    # 下载失败时使用原始 URL
                    logger.warning(f"下载失败，使用原始 URL: {img_url[:80]}")
                    img_info['thumbnail_url'] = img_url  # 使用原始 URL
                    preview_images.append(img_info)

            except Exception as e:
                logger.warning(f"生成预览失败: {e}, 使用原始 URL")
                img_info['thumbnail_url'] = img_url  # 备用
                preview_images.append(img_info)

        # 更新会话数据中的图片列表
        session_data['images'] = preview_images

        # 保存会话文件
        session_file = os.path.join(session_dir, 'session.json')
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        logger.info(f"会话创建成功: {session_id}, 图片数量: {len(preview_images)}")

        return jsonify({
            'success': True,
            'session_id': session_id,
            'data': {
                'title': session_data['title'],
                'price': session_data['price'],
                'images': session_data['images']
            }
        })

    except Exception as e:
        logger.error(f"创建会话失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/session-preview/<session_id>/<filename>')
@require_auth
def get_session_preview(session_id: str, filename: str):
    """获取会话预览图"""
    # 转换 URL 格式: preview_1.jpg
    if not filename.startswith('preview_'):
        filename = f'preview_{filename}'
    preview_path = os.path.join(app.config['TEMP_DIR'], session_id, filename)
    if not os.path.exists(preview_path):
        logger.error(f"预览图不存在: {preview_path}")
        return 'Not found', 404
    return send_file(preview_path, mimetype='image/jpeg')


@app.route('/api/session/<session_id>')
@require_auth
def get_session(session_id: str):
    """获取会话信息"""
    session_file = os.path.join(app.config['TEMP_DIR'], session_id, 'session.json')
    if not os.path.exists(session_file):
        return jsonify({'success': False, 'error': '会话不存在'}), 404

    with open(session_file, 'r', encoding='utf-8') as f:
        session_data = json.load(f)

    # 不返回完整 URL 图片，只返回预览
    return jsonify({
        'success': True,
        'data': session_data
    })


@app.route('/api/session/<session_id>/images/reorder', methods=['POST'])
@require_auth
def reorder_images(session_id: str):
    """
    调整图片顺序

    请求体:
    {
        "image_ids": ["id1", "id2", "id3"]  // 新的顺序
    }
    """
    session_file = os.path.join(app.config['TEMP_DIR'], session_id, 'session.json')
    if not os.path.exists(session_file):
        return jsonify({'success': False, 'error': '会话不存在'}), 404

    try:
        data = request.get_json()
        image_ids = data.get('image_ids', [])

        with open(session_file, 'r', encoding='utf-8') as f:
            session_data = json.load(f)

        # 创建 ID 到图片的映射
        all_images = session_data['images'] + session_data.get('custom_images', [])
        id_to_image = {img['id']: img for img in all_images}

        # 按新顺序排列
        reordered = []
        for img_id in image_ids:
            if img_id in id_to_image:
                reordered.append(id_to_image[img_id])

        # 更新会话中的图片（只保留原始图片的顺序，不包含自定义图片）
        session_data['images'] = reordered

        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        return jsonify({
            'success': True,
            'images': reordered
        })

    except Exception as e:
        logger.error(f"调整图片顺序失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/images/<image_id>', methods=['DELETE'])
@require_auth
def delete_image(session_id: str, image_id: str):
    """删除图片"""
    session_file = os.path.join(app.config['TEMP_DIR'], session_id, 'session.json')
    if not os.path.exists(session_file):
        return jsonify({'success': False, 'error': '会话不存在'}), 404

    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            session_data = json.load(f)

        # 从原始图片中删除
        original_images = [img for img in session_data['images'] if img['id'] != image_id]
        session_data['images'] = original_images

        # 从自定义图片中删除
        custom_images = [img for img in session_data.get('custom_images', []) if img['id'] != image_id]
        session_data['custom_images'] = custom_images

        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        return jsonify({
            'success': True,
            'images': original_images + custom_images
        })

    except Exception as e:
        logger.error(f"删除图片失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/images/add', methods=['POST'])
@require_auth
def add_image(session_id: str):
    """
    添加图片（通过 Base64 上传）

    请求体:
    {
        "image_data": "data:image/jpeg;base64,xxxxx"  // Base64 编码的图片
    }
    """
    session_file = os.path.join(app.config['TEMP_DIR'], session_id, 'session.json')
    if not os.path.exists(session_file):
        return jsonify({'success': False, 'error': '会话不存在'}), 404

    try:
        data = request.get_json()
        image_data = data.get('image_data', '')

        if not image_data:
            return jsonify({'success': False, 'error': '缺少图片数据'}), 400

        # 解析 Base64
        if ',' in image_data:
            mime_type, base64_data = image_data.split(',', 1)
        else:
            base64_data = image_data

        # 解码
        try:
            img_bytes = base64.b64decode(base64_data)
        except Exception:
            return jsonify({'success': False, 'error': '无效的 Base64 数据'}), 400

        # 验证图片
        processor = ImageDownloader()
        if not processor.processor._validate_content(img_bytes):
            return jsonify({'success': False, 'error': '无效的图片格式'}), 400

        # 保存图片
        img_id = str(uuid.uuid4())[:8]
        session_dir = os.path.join(app.config['TEMP_DIR'], session_id)
        img_path = os.path.join(session_dir, f'custom_{img_id}.jpg')
        thumbnail_path = os.path.join(session_dir, f'custom_{img_id}_thumb.jpg')

        from PIL import Image
        import io

        # 保存原图
        img = Image.open(io.BytesIO(img_bytes))
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        img.save(img_path, 'JPEG', quality=95)

        # 生成缩略图
        img_thumb = Image.open(io.BytesIO(img_bytes))
        if img_thumb.mode != 'RGB':
            img_thumb = img_thumb.convert('RGB')
        img_thumb.thumbnail((400, 500), Image.Resampling.LANCZOS)
        img_thumb.save(thumbnail_path, 'JPEG', quality=85)

        # 更新会话
        with open(session_file, 'r', encoding='utf-8') as f:
            session_data = json.load(f)

        new_image = {
            'id': img_id,
            'url': img_path,
            'thumbnail_url': f'/api/session/{session_id}/custom/{img_id}_thumb.jpg',
            'is_custom': True,
            'order': len(session_data.get('custom_images', []))
        }

        if 'custom_images' not in session_data:
            session_data['custom_images'] = []
        session_data['custom_images'].append(new_image)

        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        return jsonify({
            'success': True,
            'image': new_image
        })

    except Exception as e:
        logger.error(f"添加图片失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/session/<session_id>/custom/<filename>')
def get_custom_image(session_id: str, filename: str):
    """获取自定义图片"""
    img_path = os.path.join(app.config['TEMP_DIR'], session_id, filename)
    if not os.path.exists(img_path):
        return 'Not found', 404
    return send_file(img_path, mimetype='image/jpeg')


@app.route('/api/generate', methods=['POST'])
@require_auth
def generate_video():
    """
    生成视频（使用会话中已编辑的图片）

    支持 JSON 或 FormData 请求:
    - session_id: 会话ID (必填)
    - duration_per_image: 每张图片时长 (可选, 默认2.5)
    - price: 价格 (可选, 覆盖抓取的价格)
    - audio: 音频文件 (可选, MP3/WAV)
    """
    try:
        # ========== 排队功能 ==========
        # 判断请求类型
        content_type = request.content_type or ''
        
        # 提前获取 session_id（用于创建队列任务）
        if 'multipart/form-data' in content_type:
            session_id = request.form.get('session_id')
        else:
            data = request.get_json() or {}
            session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({'success': False, 'error': '缺少 session_id'}), 400
        
        # 将任务加入队列
        task_id = task_queue.add_task(session_id)
        logger.info(f"任务已加入队列: {task_id}, 会话: {session_id}")
        
        # 获取队列位置
        position = task_queue.get_pending_position(task_id)
        queue_info = task_queue.get_queue_info()
        
        # 判断是否需要等待（如果前面有任务在处理）
        if position > 1 or queue_info['processing'] > 0:
            # 返回队列状态，让前端轮询
            return jsonify({
                'success': True,
                'queued': True,
                'task_id': task_id,
                'position': position,
                'message': f'任务已加入队列，您前面还有 {position - 1} 个任务'
            }), 202
        
        # ========== 开始处理 ==========
        # 更新任务状态为处理中
        task_queue.update_task_status(task_id, TaskStatus.PROCESSING, progress=0)
        
        # 判断请求类型

        if 'multipart/form-data' in content_type:
            # FormData 请求（包含音频文件）
            session_id = request.form.get('session_id')
            duration_per_image = float(request.form.get('duration_per_image', 2.5))
            price = request.form.get('price', '')
            audio_file = request.files.get('audio')
        else:
            # JSON 请求
            data = request.get_json() or {}
            session_id = data.get('session_id')
            duration_per_image = data.get('duration_per_image', 2.5)
            price = data.get('price', '')
            audio_file = None

        if not session_id:
            return jsonify({'success': False, 'error': '缺少 session_id'}), 400

        # 读取会话数据
        session_file = os.path.join(app.config['TEMP_DIR'], session_id, 'session.json')
        if not os.path.exists(session_file):
            return jsonify({'success': False, 'error': '会话不存在，请重新抓取'}), 404

        with open(session_file, 'r', encoding='utf-8') as f:
            session_data = json.load(f)

        title = session_data.get('title', '')
        # 如果请求中没有提供价格，使用会话中的价格
        if not price:
            price = session_data.get('price', '')

        # 保存音频文件（如果有）
        audio_path = None
        use_default_audio = request.form.get('use_default_audio') == 'true'
        logger.info(f"接收到的参数 - use_default_audio: {use_default_audio}, audio_file: {audio_file is not None}")

        if audio_file:
            # 用户上传的音频
            audio_path = os.path.join(app.config['TEMP_DIR'], f"{session_id}_audio.mp3")
            audio_file.save(audio_path)
            logger.info(f"保存音频文件: {audio_path}")
        elif use_default_audio:
            # 使用默认音频
            default_audio = os.path.join(app.root_path, 'static', 'default_music.mp3')
            logger.info(f"检查默认音频路径: {default_audio}, 存在: {os.path.exists(default_audio)}")
            if os.path.exists(default_audio):
                audio_path = default_audio
                logger.info(f"使用默认音频: {audio_path}")

        # 获取所有图片（原始 + 自定义）
        all_images = session_data.get('images', []) + session_data.get('custom_images', [])

        if not all_images:
            return jsonify({'success': False, 'error': '没有可用的图片'}), 400

        logger.info(f"开始生成视频，会话: {session_id}, 图片数量: {len(all_images)}")

        # 创建输出目录
        task_dir = os.path.join(app.config['TEMP_DIR'], f"{session_id}_output")
        output_dir = os.path.join(app.config['OUTPUT_DIR'], task_id)
        os.makedirs(task_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        # 下载并处理所有图片
        downloader = ImageDownloader(max_images=8)
        processed_images = []
        original_urls = []

        for img_info in all_images[:8]:  # 最多 8 张
            url = img_info.get('url', '')
            if not url:
                continue

            # 如果是自定义图片（本地路径），直接处理
            if img_info.get('is_custom') and os.path.exists(url):
                try:
                    processor = ImageDownloader().processor
                    img = processor.process_image(open(url, 'rb').read())
                    if img:
                        output_path = os.path.join(task_dir, f'frame_{len(processed_images) + 1}.jpg')
                        img.save(output_path, 'JPEG', quality=95)
                        processed_images.append(output_path)
                except Exception as e:
                    logger.warning(f"处理自定义图片失败: {e}")
                continue

            # 原始图片通过 URL 下载
            img_data = downloader.processor.download_and_validate(url)
            if img_data:
                img = downloader.processor.process_image(img_data)
                if img:
                    output_path = os.path.join(task_dir, f'frame_{len(processed_images) + 1}.jpg')
                    img.save(output_path, 'JPEG', quality=95)
                    processed_images.append(output_path)
                    original_urls.append(url)

        if not processed_images:
            return jsonify({'success': False, 'error': '没有成功处理任何图片'}), 500

        logger.info(f"成功处理 {len(processed_images)} 张图片")

        # 生成预览图
        preview_dir = os.path.join(output_dir, 'preview')
        os.makedirs(preview_dir, exist_ok=True)
        preview_urls = []

        for i, img_path in enumerate(processed_images[:8]):
            preview_path = os.path.join(preview_dir, f'preview_{i + 1}.jpg')
            try:
                from PIL import Image
                img = Image.open(img_path)
                img.thumbnail((400, 500), Image.Resampling.LANCZOS)
                img.save(preview_path, 'JPEG', quality=85)
                preview_urls.append(f'/api/preview/{task_id}/preview_{i + 1}.jpg')
            except Exception as e:
                logger.warning(f"生成预览图失败: {e}")

        # 生成视频
        video_path = os.path.join(output_dir, 'output.mp4')
        generator = VideoGenerator()
        success = generator.generate(
            image_paths=processed_images,
            output_path=video_path,
            title=title,
            price=price,
            duration_per_image=duration_per_image,
            audio_path=audio_path
        )

        if not success:
            return jsonify({'success': False, 'error': '视频生成失败'}), 500

        # 验证视频
        if not os.path.exists(video_path) or os.path.getsize(video_path) < 1000:
            return jsonify({'success': False, 'error': '生成的视频无效'}), 500

        logger.info(f"视频生成成功: {video_path}")

        # 更新任务状态为完成
        task_queue.update_task_status(task_id, TaskStatus.COMPLETED, progress=100, result={
            'video_url': f'/api/download/{task_id}',
            'preview_images': preview_urls
        })

        # 清理旧任务，只保留最近10个
        cleanup_old_files(max_tasks=10)

        return jsonify({
            'success': True,
            'task_id': task_id,
            'video_url': f'/api/download/{task_id}',
            'preview_images': preview_urls
        })

    except Exception as e:
        logger.error(f"生成视频失败: {e}")
        # 更新任务状态为失败
        if 'task_id' in dir() and task_id:
            task_queue.update_task_status(task_id, TaskStatus.FAILED, error=str(e))
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ 保留的旧接口（兼容）============

@app.route('/api/status/<task_id>')
def check_status(task_id: str):
    """检查任务状态"""
    output_dir = os.path.join(app.config['OUTPUT_DIR'], task_id)
    video_path = os.path.join(output_dir, 'output.mp4')

    if os.path.exists(video_path):
        return jsonify({
            'success': True,
            'status': 'completed',
            'video_url': f'/api/download/{task_id}'
        })
    else:
        return jsonify({
            'success': True,
            'status': 'processing'
        })


@app.route('/api/download/<task_id>')
def download_video(task_id: str):
    """下载视频"""
    video_path = os.path.join(app.config['OUTPUT_DIR'], task_id, 'output.mp4')
    if not os.path.exists(video_path):
        return jsonify({'success': False, 'error': '视频不存在'}), 404

    return send_file(
        video_path,
        mimetype='video/mp4',
        as_attachment=True,
        download_name=f'product_video_{task_id}.mp4'
    )


@app.route('/api/stream/<task_id>')
def stream_video(task_id: str):
    """流式播放视频"""
    video_path = os.path.join(app.config['OUTPUT_DIR'], task_id, 'output.mp4')
    if not os.path.exists(video_path):
        return jsonify({'success': False, 'error': '视频不存在'}), 404

    def generate():
        with open(video_path, 'rb') as f:
            while chunk := f.read(1024 * 1024):
                yield chunk

    return Response(
        generate(),
        mimetype='video/mp4',
        headers={'Content-Length': os.path.getsize(video_path)}
    )


@app.route('/api/preview/<task_id>')
def get_preview(task_id: str):
    """获取预览图列表"""
    preview_dir = os.path.join(app.config['OUTPUT_DIR'], task_id, 'preview')
    if not os.path.exists(preview_dir):
        return jsonify({'success': True, 'images': []})

    images = [
        f'/api/preview/{task_id}/{f}'
        for f in sorted(os.listdir(preview_dir))
        if f.endswith(('.jpg', '.jpeg', '.png'))
    ]
    return jsonify({'success': True, 'images': images})


@app.route('/api/preview/<task_id>/<filename>')
def get_preview_image(task_id: str, filename: str):
    """获取单个预览图"""
    preview_path = os.path.join(app.config['OUTPUT_DIR'], task_id, 'preview', filename)
    if not os.path.exists(preview_path):
        return 'Not found', 404
    return send_file(preview_path, mimetype='image/jpeg')


@app.route('/api/cleanup', methods=['POST'])
def cleanup_task():
    """清理任务"""
    data = request.get_json()
    task_id = data.get('task_id')
    session_id = data.get('session_id')

    try:
        if task_id:
            for base_dir in [app.config['TEMP_DIR'], app.config['OUTPUT_DIR']]:
                path = os.path.join(base_dir, task_id)
                if os.path.exists(path):
                    shutil.rmtree(path)

        if session_id:
            path = os.path.join(app.config['TEMP_DIR'], session_id)
            if os.path.exists(path):
                shutil.rmtree(path)

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/health')
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat()
    })


# ============ 排队功能接口 ============

@app.route('/api/queue/info')
def get_queue_info():
    """获取队列信息"""
    info = task_queue.get_queue_info()
    return jsonify({
        'success': True,
        **info
    })


@app.route('/api/queue/status/<task_id>')
def get_queue_status(task_id: str):
    """获取任务在队列中的状态"""
    task = task_queue.get_task(task_id)
    
    if not task:
        return jsonify({
            'success': False,
            'error': '任务不存在'
        }), 404
    
    position = task_queue.get_pending_position(task_id)
    
    return jsonify({
        'success': True,
        'task_id': task.task_id,
        'status': task.status.value,
        'progress': task.progress,
        'position': position if task.status == TaskStatus.PENDING else 0,
        'error': task.error,
        'created_at': task.created_at.isoformat() if task.created_at else None,
        'started_at': task.started_at.isoformat() if task.started_at else None,
        'completed_at': task.completed_at.isoformat() if task.completed_at else None
    })


def create_app():
    """创建应用实例"""
    return app


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
