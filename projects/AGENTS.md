# Link2Reels - 项目开发规范

## 项目概述

Link2Reels 是一个基于 Flask + MoviePy 的 Shopify 产品链接 → 自动生成短视频系统。

### 核心功能
- 输入 Shopify 产品链接
- 自动抓取产品数据（标题、图片、价格）
- 下载并验证图片（过滤非图片/视频/GIF/无效URL）
- 生成短视频（图片序列 + 文字 + 音频）
- 提供 Web 界面进行操作和下载

## 技术栈

- **后端**: Python 3.12 + Flask 3.0 + Flask-CORS
- **数据抓取**: requests + BeautifulSoup4 + lxml
- **图片处理**: Pillow
- **视频生成**: MoviePy
- **前端**: HTML5 + CSS3 + Vanilla JavaScript

## 目录结构

```
/workspace/projects/
├── app.py                 # Flask 应用主入口
├── requirements.txt       # Python 依赖
├── .coze                  # Coze 项目配置
├── app/
│   ├── scraper.py         # 产品信息抓取模块
│   ├── image_processor.py # 图片处理与验证模块
│   ├── video_generator.py # 视频生成模块
│   └── task_queue.py      # 任务排队模块
├── templates/
│   └── index.html         # 前端页面
├── static/                # 静态资源
├── output/                # 生成的视频输出目录
└── temp/                  # 临时文件目录
```

## 启动命令

### 开发环境
```bash
pip3 install -r requirements.txt
python3 app.py
# 或
python3 -m flask run --host=0.0.0.0 --port=5000
```

### 生产环境
```bash
pip3 install -r requirements.txt
gunicorn -w 4 -b 0.0.0.0:5000 app:create_app()
```

## API 接口

### 1. 生成视频
```
POST /api/generate
Content-Type: application/json

{
    "url": "https://shop.myshopify.com/products/xxx",
    "duration_per_image": 2.5
}

Response:
{
    "success": true,
    "task_id": "xxx",
    "video_url": "/api/download/xxx",
    "preview_images": [...]
}
```

### 2. 检查状态
```
GET /api/status/{task_id}

Response:
{
    "success": true,
    "status": "completed" | "processing"
}
```

### 3. 下载视频
```
GET /api/download/{task_id}
```

### 4. 流式播放
```
GET /api/stream/{task_id}
```

### 5. 获取产品信息（预览）
```
POST /api/product-info
Content-Type: application/json

{
    "url": "https://shop.myshopify.com/products/xxx"
}
```

### 6. 健康检查
```
GET /health

Response:
{
    "status": "ok",
    "timestamp": "..."
}
```

### 7. 获取队列信息
```
GET /api/queue/info

Response:
{
    "success": true,
    "total": 5,
    "pending": 2,
    "processing": 1,
    "completed": 2,
    "failed": 0,
    "max_concurrent": 1
}
```

### 8. 获取任务排队状态
```
GET /api/queue/status/{task_id}

Response:
{
    "success": true,
    "task_id": "xxx",
    "status": "pending" | "processing" | "completed" | "failed",
    "position": 2,
    "progress": 50,
    "error": null
}
```
```

## 图片处理规则

### 布局规则（Cover 模式）
- **画布固定**: 1000 × 1250 像素
- **缩放逻辑**: `scale = max(1000 / img_width, 1250 / img_height)`
- **保证**: 至少一个方向完全贴边，另一个方向居中
- **居中计算**:
  - `x_offset = (new_width - 1000) // 2`
  - `y_offset = (new_height - 1250) // 2`

### 验证机制
1. 扩展名过滤（jpg/jpeg/png/webp）
2. 排除视频文件（mp4/mov/avi/webm）
3. 排除 GIF
4. 文件头验证（JPEG/PNG/WebP）
5. PIL 完整性验证
6. 下载失败自动跳过
7. 最多使用 8 张有效图片

## 视频生成规则

### 输出规格
- **分辨率**: 1000 × 1250 像素（竖屏）
- **帧率**: 30 FPS
- **编码**: H264 + AAC
- **格式**: MP4

### 叠加层
- **价格标签**: 右上角
  - 半透明灰白色背景：`rgba(245, 245, 245, 200)`
  - 圆角矩形：`radius=12px`
  - 文字颜色：`rgb(30, 30, 30)`
- **标题标签**: 底部居中（仅第一张显示）

### 特效
- 淡入淡出：每张图片 0.2 秒
- 转场：支持

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `PORT` | 服务端口 | `5000` |
| `TEMP_DIR` | 临时文件目录 | `/tmp/link2reels` |
| `OUTPUT_DIR` | 输出文件目录 | `/workspace/projects/output` |

## 故障排查

### 常见问题

1. **ModuleNotFoundError**
   - 确保已运行 `pip3 install -r requirements.txt`
   - 检查 Python 路径配置

2. **视频生成失败**
   - 检查 ffmpeg 是否安装：`which ffmpeg`
   - 查看日志文件：`tail -f /app/work/logs/bypass/app.log`

3. **图片下载失败**
   - 检查网络连接
   - 确认 URL 可访问
   - 检查图片格式是否被支持

### 日志位置
- `/app/work/logs/bypass/app.log` - 应用日志

## 开发规范

### 代码风格
- Python: PEP 8
- 使用类型注解
- 所有函数必须有文档字符串
- 异常处理必须包含具体错误信息

### Git 提交规范
```
feat: 新功能
fix: Bug 修复
docs: 文档更新
refactor: 代码重构
test: 测试相关
chore: 构建/工具相关
```
