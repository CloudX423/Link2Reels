# Link2Reels - Shopify产品视频自动生成器

> 开发者: Cloud

## 项目简介

Link2Reels 是一个基于 Flask + MoviePy 的自动化视频生成系统，专门用于将 Shopify 产品页面转换为适合社交媒体传播的短视频。

**核心功能**: 输入Shopify产品链接 → 自动抓取产品信息 → 生成精美短视频

## 功能特性

### 🚀 自动化流程
- **智能抓取**: 自动解析Shopify产品页面，提取标题、图片、价格等关键信息
- **图片验证**: 多重验证机制确保图片质量，过滤无效文件
- **视频生成**: 一键生成专业级短视频，支持转场效果和背景音乐

### 🎨 专业设计
- **竖屏优化**: 1000×1250像素专为社交媒体设计
- **智能布局**: Cover模式自动适配图片，确保最佳展示效果
- **视觉增强**: 价格标签、产品标题等叠加层设计

### ⚡ 高效处理
- **任务队列**: 支持并发处理，实时监控任务状态
- **资源管理**: 自动清理旧文件，优化存储空间
- **API接口**: 完整的RESTful API，方便集成使用

## 技术栈

### 后端技术
- **Web框架**: Flask 3.0 + Flask-CORS
- **数据抓取**: requests + BeautifulSoup4 + lxml
- **图片处理**: Pillow
- **视频生成**: MoviePy

### 核心模块
- `scraper.py` - 产品信息抓取模块
- `image_processor.py` - 图片处理与验证模块
- `video_generator.py` - 视频生成模块
- `task_queue.py` - 任务队列管理模块

## 快速开始

### 环境要求
- Python 3.8+
- FFmpeg (视频编码依赖)

### 安装步骤

1. **克隆项目**
```bash
git clone <repository-url>
cd Link2Reels/projects
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **启动服务**
```bash
python app.py
```

4. **访问应用**
打开浏览器访问: `http://localhost:5000`

### Docker 部署
```bash
# 构建镜像
docker build -t link2reels .

# 运行容器
docker run -p 5000:5000 link2reels
```

## 使用指南

### Web界面使用
1. 在首页输入Shopify产品链接
2. 点击"生成预览"查看产品信息
3. 确认无误后点击"生成视频"
4. 等待处理完成后下载视频文件

### API接口使用

#### 1. 生成视频
```bash
curl -X POST http://localhost:5000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"url": "https://shop.myshopify.com/products/your-product"}'
```

#### 2. 检查任务状态
```bash
curl http://localhost:5000/api/status/{task_id}
```

#### 3. 下载视频
```bash
curl http://localhost:5000/api/download/{task_id} -o video.mp4
```

## 项目结构

```
Link2Reels/
├── projects/                 # 主项目目录
│   ├── app.py               # Flask应用主入口
│   ├── requirements.txt     # Python依赖
│   ├── app/                 # 核心模块
│   │   ├── scraper.py       # 产品信息抓取
│   │   ├── image_processor.py # 图片处理
│   │   ├── video_generator.py # 视频生成
│   │   └── task_queue.py    # 任务队列
│   ├── templates/           # 前端模板
│   │   ├── index.html       # 主页面
│   │   └── login.html       # 登录页面
│   ├── static/              # 静态资源
│   ├── output/              # 生成的视频文件
│   └── assets/              # 资源文件
├── README.md                # 项目说明
└── AGENTS.md               # 开发规范
```

## 配置说明

### 环境变量
```bash
# 服务端口
PORT=5000

# 临时文件目录
TEMP_DIR=/tmp/link2reels

# 输出文件目录
OUTPUT_DIR=/tmp/link2reels/output

# 认证配置（可选）
AUTH_ENABLED=true
AUTH_PASSWORD=your_password
```

### 视频参数配置
- **分辨率**: 1000×1250像素（竖屏）
- **帧率**: 30 FPS
- **每张图片时长**: 2.5秒（可配置）
- **转场效果**: 0.2秒淡入淡出

## 故障排除

### 常见问题

1. **依赖安装失败**
   ```bash
   # 确保使用正确的Python版本
   python --version
   
   # 清理缓存后重试
   pip cache purge
   pip install -r requirements.txt
   ```

2. **视频生成失败**
   - 检查FFmpeg是否安装: `ffmpeg -version`
   - 查看应用日志获取详细错误信息

3. **图片下载失败**
   - 确认产品链接可正常访问
   - 检查网络连接状态
   - 验证图片格式是否被支持

### 日志查看
应用日志位于标准输出，可通过以下方式查看：
```bash
# 查看实时日志
tail -f /var/log/app.log

# 或直接查看控制台输出
python app.py
```

## 开发贡献

### 代码规范
- 遵循PEP 8 Python代码规范
- 使用类型注解提高代码可读性
- 所有函数必须包含文档字符串
- 完善的异常处理机制

### 提交规范
```
feat: 新功能
fix: Bug修复
docs: 文档更新
refactor: 代码重构
test: 测试相关
chore: 构建/工具相关
```

## 许可证

本项目采用 MIT 许可证，详见 LICENSE 文件。

## 联系方式

- 开发者: Cloud
- 项目仓库: [GitHub Repository]
- 问题反馈: 请通过GitHub Issues提交

---

**注意**: 本项目仅供学习和研究使用，请遵守相关平台的使用条款和法律法规。