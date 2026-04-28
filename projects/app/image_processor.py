"""
Image Processor Module

图片下载、验证和处理模块
"""

import io
import os
import logging
from typing import List, Optional, Tuple
from pathlib import Path

import requests
from PIL import Image

logger = logging.getLogger(__name__)


class ImageProcessor:
    """图片处理器"""

    TARGET_WIDTH = 1000
    TARGET_HEIGHT = 1250
    VALID_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/',
        })

    def download_and_validate(self, url: str, timeout: int = 10) -> Optional[bytes]:
        """下载并验证图片"""
        if not url:
            logger.warning("图片 URL 为空")
            return None

        try:
            logger.info(f"正在下载图片: {url[:100]}...")

            response = self.session.get(url, timeout=timeout, stream=True)
            response.raise_for_status()

            content = response.content
            content_length = len(content)

            if content_length < 500:
                logger.warning(f"图片太小 ({content_length} bytes): {url[:80]}")
                return None

            logger.info(f"下载成功，内容大小: {content_length} bytes")

            # 内容验证
            if not self._validate_content(content):
                logger.warning(f"图片内容验证失败: {url[:80]}")
                return None

            # PIL 验证
            if not self._validate_with_pil(content):
                logger.warning(f"PIL 验证失败: {url[:80]}")
                return None

            return content

        except requests.RequestException as e:
            logger.warning(f"下载失败: {url[:80]}, 错误: {e}")
            return None
        except Exception as e:
            logger.warning(f"图片处理异常: {url[:80]}, 错误: {e}")
            return None

    def _validate_content(self, content: bytes) -> bool:
        """验证图片内容"""
        if len(content) < 12:
            return False

        # JPEG
        if content[:2] == b'\xff\xd8':
            return True

        # PNG
        if content[:8] == b'\x89PNG\r\n\x1a\n':
            return True

        # WebP
        if content[:4] == b'RIFF' and content[8:12] == b'WEBP':
            return True

        # GIF
        if content[:6] in (b'GIF87a', b'GIF89a'):
            return True

        # BMP
        if content[:2] == b'BM':
            return True

        return False

    def _validate_with_pil(self, content: bytes) -> bool:
        """使用 PIL 验证图片"""
        try:
            img = Image.open(io.BytesIO(content))

            # 检查格式
            format_ok = img.format in ('JPEG', 'PNG', 'WEBP', 'GIF', 'BMP')
            if not format_ok:
                logger.warning(f"不支持的图片格式: {img.format}")
                # 不拒绝，尝试继续

            # 完整性检查
            img.verify()

            # 重新打开
            img = Image.open(io.BytesIO(content))

            # 检查尺寸
            if img.width < 50 or img.height < 50:
                logger.warning(f"图片尺寸太小: {img.width}x{img.height}")
                return False

            logger.info(f"图片验证通过: {img.format}, {img.width}x{img.height}")
            return True

        except Exception as e:
            logger.warning(f"PIL 验证异常: {e}")
            return False

    def process_image(self, image_data: bytes, background_color: Tuple[int, int, int] = (240, 240, 240)) -> Optional[Image.Image]:
        """
        处理图片以适配目标尺寸（Contain 规则 - 完整显示不裁剪）

        规则：
        - 画布固定：1000 × 1250
        - 缩放：按比例缩放，保证图片完整显示
        - 居中放置，未填充区域用背景色填充
        """
        try:
            img = Image.open(io.BytesIO(image_data))

            # 转换 RGBA/LA/P 模式
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, background_color)
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode == 'RGBA':
                    background.paste(img, mask=img.split()[-1])
                else:
                    background.paste(img)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # Contain 缩放（完整显示，不裁剪）
            scale = min(
                self.TARGET_WIDTH / img.width,
                self.TARGET_HEIGHT / img.height
            )

            new_width = int(img.width * scale)
            new_height = int(img.height * scale)

            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # 创建目标尺寸的画布（浅灰色背景）
            canvas = Image.new('RGB', (self.TARGET_WIDTH, self.TARGET_HEIGHT), background_color)

            # 居中粘贴图片
            x_offset = (self.TARGET_WIDTH - new_width) // 2
            y_offset = (self.TARGET_HEIGHT - new_height) // 2
            canvas.paste(img, (x_offset, y_offset))

            return canvas

        except Exception as e:
            logger.error(f"图片处理失败: {e}")
            return None


class ImageDownloader:
    """图片批量下载器"""

    def __init__(self, max_images: int = 8):
        self.max_images = max_images
        self.processor = ImageProcessor()

    def download_images(self, urls: List[str], save_dir: str, prefix: str = "img") -> List[str]:
        """下载并处理多张图片"""
        Path(save_dir).mkdir(parents=True, exist_ok=True)

        saved_paths = []
        valid_urls = self._filter_urls(urls)

        logger.info(f"开始下载 {len(valid_urls)} 张图片...")

        for i, url in enumerate(valid_urls[:self.max_images]):
            try:
                img = self.processor.download_and_process(url)
                if not img:
                    logger.warning(f"跳过无效图片: {url[:80]}")
                    continue

                filename = f"{prefix}_{i + 1:02d}.jpg"
                filepath = os.path.join(save_dir, filename)
                img.save(filepath, 'JPEG', quality=95)
                saved_paths.append(filepath)
                logger.info(f"已保存: {filepath}")

            except Exception as e:
                logger.warning(f"处理图片失败: {url[:80]}, 错误: {e}")
                continue

        logger.info(f"成功下载 {len(saved_paths)} 张图片")
        return saved_paths

    def _filter_urls(self, urls: List[str]) -> List[str]:
        """过滤有效的图片 URL"""
        valid = []
        for url in urls:
            if not url or not isinstance(url, str):
                continue

            url_lower = url.lower()

            # 排除视频和 GIF
            if any(ext in url_lower for ext in ['.mp4', '.mov', '.avi', '.webm', '.gif', '/video/']):
                continue

            # 必须包含图片扩展名或是 Shopify CDN
            if any(ext in url_lower for ext in ImageProcessor.VALID_EXTENSIONS):
                valid.append(url)
            elif 'cdn.shopify.com' in url_lower:
                valid.append(url)

        return valid


def download_product_images(urls: List[str], save_dir: str, prefix: str = "product", max_images: int = 8) -> List[str]:
    """便捷函数"""
    downloader = ImageDownloader(max_images=max_images)
    return downloader.download_images(urls, save_dir, prefix)


def create_thumbnail(image_path: str, output_path: str, max_size: Tuple[int, int] = (300, 375)) -> bool:
    """创建缩略图"""
    try:
        img = Image.open(image_path)
        ratio = min(max_size[0] / img.width, max_size[1] / img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.Resampling.LANCZOS)
        img.save(output_path, 'JPEG', quality=85)
        return True
    except Exception as e:
        logger.error(f"创建缩略图失败: {e}")
        return False
