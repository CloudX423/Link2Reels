"""
Video Generator Module

使用 MoviePy 生成产品展示视频
图片序列 + 文字 + 可选音频
"""

import os
import logging
from typing import List, Optional, Tuple, Dict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import numpy as np
import moviepy.audio.fx as afx

# MoviePy 配置
try:
    import moviepy as mp
    import moviepy.audio.fx as afx
    from moviepy import (
        ImageClip, ColorClip, CompositeVideoClip, TextClip,
        concatenate_videoclips, vfx, afx
    )
    MOVIEPY_AVAILABLE = True
except ImportError as e:
    MOVIEPY_AVAILABLE = False
    logging.warning(f"MoviePy not available: {e}, video generation will be limited")

logger = logging.getLogger(__name__)


class VideoGenerator:
    """视频生成器"""

    # 视频参数
    WIDTH = 1000
    HEIGHT = 1250
    FPS = 30

    # 每张图片显示时长（秒）
    DEFAULT_DURATION_PER_IMAGE = 2.5

    # 字体设置
    FONT_SIZE_PRICE = 50  # 价格字体加大
    FONT_SIZE_TITLE = 40  # 标题字体加大

    # 价格标签背景
    PRICE_BG_PADDING = 16
    PRICE_BG_COLOR = (74, 28, 28, 220)  # 深酒红背景（半透明）
    PRICE_TEXT_COLOR = (255, 255, 255)  # 白色文字

    # 视频背景色
    BG_COLOR = (245, 245, 245)  # 浅灰白色背景（用于转场过渡）

    def __init__(self):
        """初始化视频生成器"""
        if not MOVIEPY_AVAILABLE:
            raise RuntimeError("MoviePy is not available. Please install moviepy.")

        # 配置 MoviePy
        self._configure_moviepy()

    def _configure_moviepy(self):
        """配置 MoviePy 设置"""
        import os
        os.environ['IMAGEIO_FFMPEG_LOGGER'] = 'ERROR'

        # 禁用某些警告
        import warnings
        warnings.filterwarnings('ignore')

    def generate(
        self,
        image_paths: List[str],
        output_path: str,
        title: Optional[str] = None,
        price: Optional[str] = None,
        duration_per_image: float = DEFAULT_DURATION_PER_IMAGE,
        transition_duration: float = 0.3,
        add_fade: bool = True,
        audio_path: Optional[str] = None,
    ) -> bool:
        """
        生成视频

        Args:
            image_paths: 处理好的图片路径列表
            output_path: 输出视频路径
            title: 产品标题（可选）
            price: 产品价格（可选）
            duration_per_image: 每张图片显示时长
            transition_duration: 转场时长
            add_fade: 是否添加淡入淡出
            audio_path: 背景音乐路径（可选）

        Returns:
            是否成功
        """
        if not image_paths:
            logger.error("没有图片可以生成视频")
            return False

        try:
            logger.info(f"开始生成视频，共 {len(image_paths)} 张图片")

            # 确保视频中有8次图片展示
            TARGET_IMAGE_COUNT = 8
            if len(image_paths) < TARGET_IMAGE_COUNT:
                # 循环补齐到8张
                original_count = len(image_paths)
                while len(image_paths) < TARGET_IMAGE_COUNT:
                    image_paths.append(image_paths[len(image_paths) % original_count])
                logger.info(f"图片循环补齐: {original_count} -> {len(image_paths)} 张")
            elif len(image_paths) > TARGET_IMAGE_COUNT:
                # 只取前8张
                image_paths = image_paths[:TARGET_IMAGE_COUNT]
                logger.info(f"图片截取前8张: {len(image_paths)} 张")

            # 创建图片剪辑
            clips = []
            for img_path in image_paths:
                clip = self._create_image_clip(
                    img_path,
                    title=title if clips == [] else None,  # 只在第一张显示标题
                    price=price,
                    duration=duration_per_image,
                    add_fade=add_fade,
                )
                if clip:
                    clips.append(clip)

            if not clips:
                logger.error("没有成功创建任何视频剪辑")
                return False

            # 连接所有剪辑（使用叠化转场）
            if len(clips) == 1:
                # 单张图片：添加淡入淡出
                if add_fade:
                    final_clip = clips[0].with_effects([vfx.FadeIn(0.3), vfx.FadeOut(0.3)])
                else:
                    final_clip = clips[0]
            else:
                # 多张图片：使用叠化转场
                final_clip = self._concatenate_with_crossfade(clips, transition_duration, add_fade)

            # 添加音频（如果有）
            if audio_path and os.path.exists(audio_path):
                audio_clip = mp.AudioFileClip(audio_path)
                video_duration = final_clip.duration

                # 确保音频长度匹配视频长度（不循环，直接截断或延长）
                if abs(audio_clip.duration - video_duration) < 0.5:
                    # 时长接近，直接使用（截断到视频长度）
                    audio_clip = audio_clip.subclipped(0, video_duration)
                elif audio_clip.duration < video_duration:
                    # 音频太短，只使用可用部分
                    audio_clip = audio_clip.subclipped(0, audio_clip.duration)
                else:
                    # 音频太长，截断
                    audio_clip = audio_clip.subclipped(0, video_duration)

                # 添加淡入淡出效果（每端0.5秒）
                fade_duration = min(0.5, video_duration / 4)
                audio_clip = audio_clip.with_effects([
                    afx.AudioFadeIn(fade_duration),
                    afx.AudioFadeOut(fade_duration)
                ])

                final_clip = final_clip.with_audio(audio_clip)

            # 确保输出目录存在
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            # 导出视频
            logger.info(f"正在导出视频到: {output_path}")
            final_clip.write_videofile(
                output_path,
                fps=self.FPS,
                codec='libx264',
                audio_codec='aac',
                audio_bitrate='192k',
                preset='medium',
                threads=4,
                logger=None,  # 禁用 MoviePy 的日志输出
            )

            # 清理资源
            final_clip.close()
            for clip in clips:
                clip.close()

            logger.info(f"视频生成完成: {output_path}")
            return True

        except Exception as e:
            logger.error(f"视频生成失败: {e}")
            return False

    def _concatenate_with_crossfade(
        self,
        clips: List['ImageClip'],
        transition_duration: float = 0.3,
        add_fade: bool = True,
    ) -> 'CompositeVideoClip':
        """使用随机转场效果连接多张图片

        转场类型（随机选择）：
        - slide_left: 从左滑入
        - slide_right: 从右滑入
        - slide_up: 从上滑入
        - slide_down: 从下滑入
        - fade: 淡入淡出

        灰色背景确保无黑屏。
        """
        if len(clips) == 0:
            raise ValueError("No clips to concatenate")

        # 计算转场时长（缩短白屏时间）
        trans_dur = min(transition_duration, clips[0].duration / 3)
        trans_dur = max(trans_dur, 0.2)  # 最小0.2秒

        # 构建场景列表：每个场景 = [背景层, 图片层 + 转场效果]
        scenes = []

        for i, clip in enumerate(clips):
            clip_dur = clip.duration
            is_first = (i == 0)
            is_last = (i == len(clips) - 1)

            # 场景时长：每张图片时长相同，不额外加分转场时长
            # 转场效果（FadeOut）在每张图片末尾 trans_dur 秒内完成
            scene_dur = clip_dur

            # 创建灰色背景层
            bg = ColorClip(size=(self.WIDTH, self.HEIGHT), color=self.BG_COLOR)
            bg = bg.with_duration(scene_dur)

            # 为非最后一张图片添加转场效果
            if not is_last and add_fade:
                # 随机选择转场类型（去掉zoom）
                import random
                transition_type = random.choice([
                    'slide_left', 'slide_right', 'slide_up', 'slide_down', 'fade'
                ])

                # 应用转场效果（MoviePy SlideIn/SlideOut 不支持缓动曲线）
                clip = self._apply_transition(clip, trans_dur, transition_type)

            # 组合场景：背景在下，图片在上
            scene = CompositeVideoClip([bg, clip], size=(self.WIDTH, self.HEIGHT), use_bgclip=False)
            scene = scene.with_duration(scene_dur)
            scenes.append(scene)

        # 如果只有一张图片，直接返回
        if len(scenes) == 1:
            return scenes[0]

        # 拼接所有场景
        result = scenes[0]
        for i in range(1, len(scenes)):
            result = concatenate_videoclips([result, scenes[i]])

        return result

    def _apply_transition(self, clip: 'ImageClip', duration: float, transition_type: str) -> 'ImageClip':
        """应用转场效果到图片

        Args:
            clip: 图片剪辑
            duration: 转场时长
            transition_type: 转场类型

        Returns:
            应用转场效果后的剪辑
        """
        if transition_type == 'slide_left':
            return clip.with_effects([
                vfx.SlideIn(duration, 'left'),
                vfx.SlideOut(duration, 'right')
            ])

        elif transition_type == 'slide_right':
            return clip.with_effects([
                vfx.SlideIn(duration, 'right'),
                vfx.SlideOut(duration, 'left')
            ])

        elif transition_type == 'slide_up':
            return clip.with_effects([
                vfx.SlideIn(duration, 'top'),
                vfx.SlideOut(duration, 'bottom')
            ])

        elif transition_type == 'slide_down':
            return clip.with_effects([
                vfx.SlideIn(duration, 'bottom'),
                vfx.SlideOut(duration, 'top')
            ])

        else:  # fade
            return clip.with_effects([
                vfx.FadeIn(duration),
                vfx.FadeOut(duration)
            ])

    def _create_image_clip(
        self,
        image_path: str,
        title: Optional[str],
        price: Optional[str],
        duration: float,
        add_fade: bool,
    ) -> Optional['ImageClip']:
        """创建单个图片剪辑"""
        try:
            # 加载图片（MoviePy 2.x 语法）
            clip = ImageClip(image_path).with_duration(duration)

            # 计算缩放比例，确保图片完整不裁剪
            # 策略：图片完整显示，最多只有一个方向顶边
            video_ratio = self.WIDTH / self.HEIGHT  # 视频宽高比
            img_ratio = clip.w / clip.h if clip.h > 0 else 1  # 图片宽高比

            if img_ratio > video_ratio:
                # 图片比视频更宽，按高度缩放（宽度会小于视频，两侧有边距）
                clip = clip.resized(height=self.HEIGHT)
            else:
                # 图片比视频更高，按宽度缩放（高度会小于视频，上下有边距）
                clip = clip.resized(width=self.WIDTH)

            # 居中放置
            clip = clip.with_position(("center", "center"))
            
            # 添加持续放大效果：每秒放大1%
            # 关键帧方案：0秒=1.0, 结束=1.01*duration，让引擎内部插值，消除逐帧计算抖动
            scale_factor = 0.01 * duration
            clip = clip.resized(lambda t, factor=scale_factor, d=duration: 1 + factor * t / d)

            # 创建叠加层（用于文字）
            overlays = []

            # 添加价格标签
            if price:
                price_overlay = self._create_price_overlay(price)
                if price_overlay:
                    overlays.append(price_overlay)

            # 添加标题
            if title:
                title_overlay = self._create_title_overlay(title)
                if title_overlay:
                    overlays.append(title_overlay)

            # 创建背景层（深色背景填充）
            bg_clip = ColorClip(size=(self.WIDTH, self.HEIGHT), color=(20, 20, 20)).with_duration(duration)

            # 居中放置
            clip = clip.with_position(("center", "center"))

            # 合成叠加层
            if overlays:
                overlay_clip = CompositeVideoClip(overlays, size=(self.WIDTH, self.HEIGHT))
                clip = CompositeVideoClip([bg_clip, clip, overlay_clip], size=(self.WIDTH, self.HEIGHT))
            else:
                clip = CompositeVideoClip([bg_clip, clip], size=(self.WIDTH, self.HEIGHT))

            # 设置时长（不在这里添加淡入淡出，叠化在连接时处理）
            clip = clip.with_duration(duration)

            return clip

        except Exception as e:
            logger.error(f"创建图片剪辑失败: {e}")
            return None

    def _create_price_overlay(self, price: str) -> Optional['ImageClip']:
        """创建价格标签叠加层"""
        try:
            # 创建带透明度的图片
            overlay_img = Image.new('RGBA', (self.WIDTH, self.HEIGHT), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay_img)

            # 尝试加载字体
            font = self._load_font(self.FONT_SIZE_PRICE)

            # 计算价格文本尺寸
            bbox = draw.textbbox((0, 0), price, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            # 位置：右上角
            x = self.WIDTH - text_width - self.PRICE_BG_PADDING * 2 - 20
            y = self.PRICE_BG_PADDING + 20

            # 绘制背景矩形
            bg_rect = (
                x - self.PRICE_BG_PADDING,
                y - self.PRICE_BG_PADDING,
                x + text_width + self.PRICE_BG_PADDING,
                y + text_height + self.PRICE_BG_PADDING
            )
            draw.rounded_rectangle(bg_rect, radius=12, fill=self.PRICE_BG_COLOR)

            # 绘制文字
            draw.text(
                (x, y),
                price,
                font=font,
                fill=self.PRICE_TEXT_COLOR
            )

            # 转换为 numpy 数组
            overlay_array = np.array(overlay_img)

            # 创建 ImageClip（MoviePy 2.x 语法）
            overlay_clip = ImageClip(overlay_array)
            # overlay_clip 的时长会在 composite 时从主剪辑继承

            return overlay_clip

        except Exception as e:
            logger.error(f"创建价格叠加层失败: {e}")
            return None

    def _create_title_overlay(self, title: str) -> Optional['ImageClip']:
        """创建标题叠加层"""
        try:
            # 截断标题
            if len(title) > 50:
                title = title[:47] + '...'

            # 创建带透明度的图片
            overlay_img = Image.new('RGBA', (self.WIDTH, self.HEIGHT), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay_img)

            # 加载字体
            font = self._load_font(self.FONT_SIZE_TITLE)

            # 计算文本尺寸
            bbox = draw.textbbox((0, 0), title, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            # 位置：底部居中
            x = (self.WIDTH - text_width) // 2
            y = self.HEIGHT - text_height - self.PRICE_BG_PADDING * 2 - 60

            # 绘制背景
            bg_rect = (
                x - self.PRICE_BG_PADDING,
                y - self.PRICE_BG_PADDING,
                x + text_width + self.PRICE_BG_PADDING,
                y + text_height + self.PRICE_BG_PADDING
            )
            draw.rounded_rectangle(bg_rect, radius=12, fill=self.PRICE_BG_COLOR)

            # 绘制文字
            draw.text(
                (x, y),
                title,
                font=font,
                fill=self.PRICE_TEXT_COLOR
            )

            # 转换为 numpy 数组
            overlay_array = np.array(overlay_img)

            # 创建 ImageClip（MoviePy 2.x 语法）
            overlay_clip = ImageClip(overlay_array)

            return overlay_clip

        except Exception as e:
            logger.error(f"创建标题叠加层失败: {e}")
            return None

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont:
        """加载字体"""
        # 字体优先级列表
        font_paths = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
            '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
            '/System/Library/Fonts/Helvetica.ttc',  # macOS
            'C:/Windows/Fonts/arial.ttf',  # Windows
        ]

        for font_path in font_paths:
            if os.path.exists(font_path):
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    continue

        # 回退到默认字体
        return ImageFont.load_default()


class VideoGeneratorSimple:
    """简化版视频生成器（不使用 MoviePy 的复杂功能）"""

    WIDTH = 1000
    HEIGHT = 1250
    FPS = 30

    def __init__(self):
        if not MOVIEPY_AVAILABLE:
            raise RuntimeError("MoviePy is not available")

    def generate(
        self,
        image_paths: List[str],
        output_path: str,
        title: Optional[str] = None,
        price: Optional[str] = None,
        duration_per_image: float = 2.5,
    ) -> bool:
        """生成视频"""
        try:
            logger.info(f"开始生成视频: {output_path}")

            clips = []
            for img_path in image_paths:
                img_clip = ImageClip(img_path).with_duration(duration_per_image)
                img_clip = img_clip.resized(height=self.HEIGHT)
                if img_clip.w < self.WIDTH:
                    img_clip = img_clip.resized(width=self.WIDTH)
                clips.append(img_clip)

            final = concatenate_videoclips(clips)

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            final.write_videofile(
                output_path,
                fps=self.FPS,
                codec='libx264',
                audio_codec='aac',
                preset='medium',
                logger=None,
            )

            return True

        except Exception as e:
            logger.error(f"视频生成失败: {e}")
            return False


def generate_product_video(
    image_paths: List[str],
    output_path: str,
    title: Optional[str] = None,
    price: Optional[str] = None,
    duration_per_image: float = 2.5,
    **kwargs
) -> bool:
    """
    便捷函数：生成产品视频

    Args:
        image_paths: 图片路径列表
        output_path: 输出路径
        title: 产品标题
        price: 产品价格
        duration_per_image: 每张图片时长

    Returns:
        是否成功
    """
    generator = VideoGenerator()
    return generator.generate(
        image_paths=image_paths,
        output_path=output_path,
        title=title,
        price=price,
        duration_per_image=duration_per_image,
        **kwargs
    )
