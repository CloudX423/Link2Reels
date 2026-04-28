"""
Product Scraper Module

支持抓取 Shopify 平台的产品页面
通过识别 Shopify 特有数据结构来判断和解析
"""

import re
import json
import logging
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ProductScraper:
    """产品信息抓取器 - 专注于 Shopify 结构"""

    VALID_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
    EXCLUDED_EXTENSIONS = {'.mp4', '.mov', '.avi', '.webm', '.gif'}

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8',
        })

    def scrape(self, url: str) -> Dict:
        """抓取产品信息"""
        url = self._normalize_url(url)
        
        try:
            # 跟随所有重定向，获取最终 URL
            response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"请求失败: {e}")
            raise ValueError(f"无法访问该链接: {e}")

        final_url = response.url
        html = response.text
        
        # 检测是否可能是 Shopify 页面
        is_shopify = self._detect_shopify(html, final_url)
        logger.info(f"检测结果: Shopify={is_shopify}, URL={final_url}")

        soup = BeautifulSoup(html, 'lxml')

        # 提取产品数据
        product_data = {
            'title': self._extract_title(soup, html),
            'price': self._extract_price(soup, html),
            'images': self._extract_images(soup, html, final_url),
            'original_url': final_url,
            'is_shopify': is_shopify,
        }

        # 验证
        if not product_data['title']:
            raise ValueError("无法提取产品标题，请确认链接是否为产品页面")
        
        if not product_data['images']:
            raise ValueError("未找到产品图片")

        logger.info(f"抓取成功: {product_data['title']}, {len(product_data['images'])} 张图片")
        return product_data

    def _normalize_url(self, url: str) -> str:
        url = url.strip()
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return url

    def _detect_shopify(self, html: str, url: str) -> bool:
        """检测页面是否为 Shopify 构建"""
        # 检查 Shopify 特征
        shopify_patterns = [
            'cdn.shopify.com',           # Shopify CDN
            'shopify.',                  # Shopify 域名/属性
            '"@type": "Product"',        # JSON-LD Product
            '"@context".*shopify',       # Shopify JSON-LD
            'data-shopify-',             # Shopify 属性
            'Shopify',                   # Shopify 引用
            'myshopify.com',             # Shopify 子域名
        ]
        
        for pattern in shopify_patterns:
            if re.search(pattern, html, re.IGNORECASE):
                return True
        
        # 检查 URL 路径模式
        path_checks = [
            '/products/',
            '/collections/.*/products/',
        ]
        
        parsed = urlparse(url)
        for pattern in path_checks:
            if re.search(pattern, parsed.path):
                return True
        
        return False

    def _extract_title(self, soup: BeautifulSoup, html: str) -> Optional[str]:
        """提取产品标题"""
        
        # 1. JSON-LD（最可靠）
        title = self._extract_from_jsonld(soup)
        if title:
            return title

        # 2. meta og:title
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title['content'].strip()

        # 3. title 标签
        title_tag = soup.find('title')
        if title_tag:
            t = title_tag.get_text(strip=True)
            # 清理常见的格式 "Product Title - Shop Name"
            if ' - ' in t:
                t = t.split(' - ')[0].strip()
            elif ' | ' in t:
                t = t.split(' | ')[0].strip()
            return t

        # 4. 常见选择器
        selectors = [
            # 通用产品标题
            'h1[class*="title" i]',
            'h1[class*="product" i]',
            'h1[class*="name" i]',
            '.product-title',
            '.product_name',
            '.product-name',
            '.productTitle',
            '.product__title',
            '.product-title h1',
            '.product-header h1',
            '.product-info h1',
            '.product-details h1',
            '.product-single h1',
            
            # Shopify specific
            '#ProductHeading',
            '#product-title',
            '[data-product-title]',
            
            # 通用
            'h1[class*="product"]',
            '.product h1',
            'article h1',
            'main h1',
            
            # 最通用
            'h1',
        ]

        for selector in selectors:
            try:
                elem = soup.select_one(selector)
                if elem:
                    t = elem.get_text(strip=True)
                    if t and 3 < len(t) < 300:
                        return t
            except Exception:
                continue

        return None

    def _extract_from_jsonld(self, soup: BeautifulSoup) -> Optional[str]:
        """从 JSON-LD 提取标题"""
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                
                for item in items:
                    # 查找 Product 类型
                    if self._is_product_type(item):
                        name = item.get('name')
                        if name:
                            return str(name).strip()
                        
                        # 尝试从 nestedProductOffer 或 offers 获取
                        offers = item.get('offers', [])
                        if offers:
                            if isinstance(offers, dict):
                                name = offers.get('name')
                                if name:
                                    return str(name).strip()
                            elif isinstance(offers, list) and offers:
                                name = offers[0].get('name')
                                if name:
                                    return str(name).strip()
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _is_product_type(self, item: dict) -> bool:
        """判断是否为产品类型"""
        item_type = item.get('@type', '')
        if isinstance(item_type, list):
            return 'Product' in item_type
        return 'Product' in str(item_type)

    def _extract_price(self, soup: BeautifulSoup, html: str) -> Optional[str]:
        """提取产品价格"""
        
        # 1. JSON-LD
        price = self._extract_price_from_jsonld(soup)
        if price:
            return price

        # 2. 从 var meta (Shopify 内联数据) 提取价格
        price = self._extract_price_from_var_meta(html)
        if price:
            return price

        # 3. meta og:price
        price_meta = soup.find('meta', property='product:price:amount')
        if price_meta and price_meta.get('content'):
            currency = soup.find('meta', property='product:price:currency')
            curr = self._get_currency_symbol(currency.get('content', 'USD') if currency else 'USD')
            return f"{curr}{price_meta['content']}"

        # 4. data 属性
        price_attrs = soup.find_all(attrs={"data-price": True})
        for elem in price_attrs:
            val = elem.get('data-price')
            if val:
                return self._format_price(val)

        # 4. 常见选择器
        selectors = [
            '.price',
            '.price-item',
            '.product-price',
            '.product__price',
            '.current-price',
            '.sale-price',
            '.special-price',
            '.regular-price',
            '[class*="price" i]',
            '[itemprop="price"]',
            '#price',
            '#product-price',
        ]

        for selector in selectors:
            try:
                elem = soup.select_one(selector)
                if elem:
                    price_text = elem.get_text(strip=True)
                    parsed = self._parse_price_text(price_text)
                    if parsed:
                        return parsed
            except Exception:
                continue

        # 5. 页面文本搜索
        price_texts = re.findall(r'[$€£¥₹]\s*[\d,]+\.?\d{0,2}', html)
        for text in price_texts[:3]:
            parsed = self._parse_price_text(text)
            if parsed and self._is_likely_price(parsed):
                return parsed

        return None

    def _extract_price_from_jsonld(self, soup: BeautifulSoup) -> Optional[str]:
        """从 JSON-LD 提取价格"""
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                
                for item in items:
                    if self._is_product_type(item):
                        offers = item.get('offers', {})
                        if not offers:
                            continue
                        
                        # 处理数组
                        if isinstance(offers, list):
                            offers = offers[0] if offers else {}
                        
                        price = offers.get('price') or offers.get('lowPrice')
                        currency = offers.get('priceCurrency', 'USD')
                        
                        if price:
                            symbol = self._get_currency_symbol(currency)
                            formatted_price = self._format_price(str(price))
                            return f"{symbol}{formatted_price[1:]}" if formatted_price.startswith('$') else f"{symbol}{formatted_price}"
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _extract_price_from_var_meta(self, html: str) -> Optional[str]:
        """从 Shopify 的 var meta 中提取价格"""
        try:
            # 查找 var meta = {...}
            match = re.search(r'var meta = ({.*?});', html, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                product = data.get('product', {})
                variants = product.get('variants', [])
                if variants and len(variants) > 0:
                    # 获取第一个变体的价格
                    variant = variants[0]
                    price = variant.get('price')
                    currency_code = 'NZD'  # 从页面获取，默认 NZD
                    
                    # 尝试从页面获取货币
                    currency_match = re.search(r'"currencyCode"\s*:\s*"([A-Z]{3})"', html)
                    if currency_match:
                        currency_code = currency_match.group(1)
                    
                    if price:
                        symbol = self._get_currency_symbol(currency_code)
                        formatted_price = self._format_price(str(price))
                        return f"{symbol}{formatted_price[1:]}" if formatted_price.startswith('$') else f"{symbol}{formatted_price}"
        except Exception:
            pass
        return None

    def _get_currency_symbol(self, currency: str) -> str:
        symbols = {
            'USD': '$', 'EUR': '€', 'GBP': '£',
            'JPY': '¥', 'CNY': '¥', 'INR': '₹',
            'AUD': 'A$', 'CAD': 'C$', 'KRW': '₩',
            'NZD': 'NZ$',  # 新西兰元
            'HKD': 'HK$',  # 港币
            'SGD': 'S$',   # 新加坡元
            'CHF': 'CHF',  # 瑞士法郎
        }
        return symbols.get(currency.upper(), currency + ' ')

    def _format_price(self, value: str) -> str:
        try:
            num = float(value)
            # 如果数值大于1000，很可能是以"分"为单位（如NZD），转换为元
            if num >= 1000:
                num = num / 100
            # 如果有小数部分则保留，最多2位；整数部分不加小数
            if num == int(num):
                return f"${int(num)}"
            else:
                return f"${num:.2f}"
        except:
            return value

    def _parse_price_text(self, text: str) -> Optional[str]:
        if not text:
            return None
        text = text.strip()
        
        # 直接匹配价格格式
        if re.match(r'^[$€£¥₹]\s*[\d,]+\.?\d*$', text):
            return text
        
        # 提取价格数字
        match = re.search(r'[$€£¥₹]?\s*([\d,]+\.?\d*)', text)
        if match:
            symbol = re.search(r'[$€£¥₹]', text)
            return f"{symbol.group() if symbol else ''}{match.group(1)}"
        
        return None

    def _is_likely_price(self, price_text: str) -> bool:
        try:
            numbers = re.findall(r'[\d,]+\.?\d*', price_text)
            if not numbers:
                return False
            price = float(numbers[0].replace(',', ''))
            return 0.01 <= price <= 100000
        except:
            return False

    def _extract_images(self, soup: BeautifulSoup, html: str, base_url: str) -> List[str]:
        """提取产品图片 - 优先从产品主图容器提取"""
        
        # 精确的产品主图容器选择器（按优先级排序）
        primary_containers = soup.select('div.product-main-slide')
        if primary_containers:
            container_images = []
            seen = set()
            seen_files = set()  # 基于文件名去重
            
            for container in primary_containers:
                images = self._extract_images_from_container(container, base_url, seen)
                for img_url in images:
                    # 提取文件名用于去重（移除查询参数）
                    filename = img_url.split('/')[-1].split('?')[0]
                    if filename not in seen_files:
                        seen_files.add(filename)
                        container_images.append(img_url)
            
            if container_images:
                logger.info(f"从产品主图容器提取到 {len(container_images)} 张图片")
                return container_images[:8]
        
        # 备选：其他产品容器
        secondary_containers = soup.select(','.join([
            'div.product-image-main', 
            'div.product-gallery',
            'div.product__media',
            'div.product-media',
            '[class*="product-gallery"]',
        ]))
        
        if secondary_containers:
            container_images = []
            seen = set()
            seen_files = set()  # 基于文件名去重
            
            for container in secondary_containers:
                images = self._extract_images_from_container(container, base_url, seen)
                for img_url in images:
                    filename = img_url.split('/')[-1].split('?')[0]
                    if filename not in seen_files:
                        seen_files.add(filename)
                        container_images.append(img_url)
            
            if container_images:
                logger.info(f"从次级产品容器提取到 {len(container_images)} 张图片")
                return container_images[:8]
        
        # 第三步：JSON-LD（Shopify 最可靠的数据源）
        logger.info("未找到专用容器，使用备选方案")
        seen = set()
        jsonld_images = self._extract_images_from_jsonld(soup, base_url, seen)
        if jsonld_images:
            logger.info(f"从 JSON-LD 提取到 {len(jsonld_images)} 张图片")
            return jsonld_images[:8]
        
        # 备选2：og:image
        og_images = []
        for meta in soup.find_all('meta', property='og:image'):
            url = meta.get('content')
            if url:
                cleaned = self._clean_url(url, base_url)
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    og_images.append(cleaned)
        
        if og_images:
            logger.info(f"从 og:image 提取到 {len(og_images)} 张图片")
            return og_images[:8]
        
        # 备选3：全页面扫描
        all_images = self._extract_all_product_images(soup, base_url, seen)
        return all_images[:8]

    def _extract_images_from_container(self, container, base_url: str, seen: set) -> List[str]:
        """从产品容器中提取图片"""
        images = []
        
        # 查找所有 img 标签
        for img in container.find_all('img'):
            # 尝试多个属性
            for attr in ['src', 'data-src', 'data-lazy-src', 'data-original', 'data-zoom-src']:
                url = img.get(attr)
                if url:
                    cleaned = self._clean_url(url, base_url)
                    if cleaned and cleaned not in seen:
                        seen.add(cleaned)
                        images.append(cleaned)
            
            # srcset 中的高分辨率图片
            srcset = img.get('srcset') or img.get('data-srcset')
            if srcset:
                # 解析 srcset，选择最高分辨率
                best_url = self._parse_srcset_best(srcset, base_url)
                if best_url and best_url not in seen:
                    seen.add(best_url)
                    images.append(best_url)
        
        # 查找 picture > source
        for picture in container.find_all('picture'):
            for source in picture.find_all('source'):
                srcset = source.get('srcset')
                if srcset:
                    best_url = self._parse_srcset_best(srcset, base_url)
                    if best_url and best_url not in seen:
                        seen.add(best_url)
                        images.append(best_url)
        
        # 查找 data-src 背景图
        for elem in container.find_all(attrs={'data-src': True}):
            url = self._clean_url(elem.get('data-src'), base_url)
            if url and url not in seen:
                seen.add(url)
                images.append(url)
        
        return images

    def _extract_all_product_images(self, soup: BeautifulSoup, base_url: str, seen: set) -> List[str]:
        """从整个页面提取产品相关图片"""
        images = []
        
        # 查找产品区域的 img
        for img in soup.find_all('img'):
            # 检查是否可能是产品图片
            class_name = img.get('class', [])
            class_str = ' '.join(class_name).lower() if class_name else ''
            
            src = img.get('src', '')
            src_lower = src.lower()
            
            # 跳过明显的非产品图片
            skip_patterns = ['logo', 'icon', 'avatar', 'badge', 'star', 'rating', 
                           'placeholder', 'spacer', 'pixel', 'tracking', '1x1',
                           'swatch', 'color-swatch']
            if any(p in class_str or p in src_lower for p in skip_patterns):
                continue
            
            # 获取最佳 URL
            best_url = None
            
            # 优先使用 data-src
            for attr in ['data-zoom-src', 'data-large-src', 'data-src', 'data-lazy-src', 'src']:
                url = img.get(attr)
                if url:
                    cleaned = self._clean_url(url, base_url)
                    if cleaned and cleaned not in seen:
                        best_url = cleaned
                        break
            
            if best_url:
                seen.add(best_url)
                images.append(best_url)
        
        return images

    def _clean_url(self, url: str, base_url: str) -> Optional[str]:
        """清理 URL：处理相对路径、协议、查询参数"""
        if not url:
            return None
        
        # 跳过明显无效的 URL
        url_lower = url.lower()
        if any(p in url_lower for p in ['/api/', '/proxy/', 'code.coze']):
            return None
        
        # 排除无效图片类型
        invalid_patterns = ['hqdefault', 'mqdefault', 'sddefault', 'maxresdefault', 'thumbnail']
        if any(p in url_lower for p in invalid_patterns):
            logger.info(f"排除无效图片类型: {url[:60]}...")
            return None
        
        # 处理协议相对 URL
        if url.startswith('//'):
            url = 'https:' + url
        # 处理相对路径
        elif url.startswith('/'):
            parsed = urlparse(base_url)
            url = f"{parsed.scheme}://{parsed.netloc}{url}"
        
        # 只保留 http/https
        if not url.startswith('http'):
            return None
        
        # 对于 Shopify URL，移除查询参数中的尺寸限制
        if 'cdn.shopify.com' in url and '/products/' in url:
            # 保留 ?v=xxx 用于缓存，但可以移除 width 参数获取原图
            if 'width=' in url:
                # 尝试获取更大尺寸
                pass
        
        return url

    def _parse_srcset_best(self, srcset: str, base_url: str) -> Optional[str]:
        """解析 srcset，选择最高分辨率的图片"""
        if not srcset:
            return None
        
        best_url = None
        best_width = 0
        
        for part in srcset.split(','):
            part = part.strip()
            if not part:
                continue
            
            tokens = part.split()
            if not tokens:
                continue
            
            url = self._clean_url(tokens[0], base_url)
            if not url:
                continue
            
            # 提取宽度
            width = 0
            if len(tokens) > 1:
                w_str = tokens[1].rstrip('wW')
                try:
                    width = int(w_str)
                except ValueError:
                    pass
            
            # 选择最高分辨率
            if width >= best_width:
                best_width = width
                best_url = url
        
        return best_url

    def _extract_images_from_jsonld(self, soup: BeautifulSoup, base_url: str, seen: set) -> List[str]:
        """从 JSON-LD 提取图片"""
        images = []
        
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                
                for item in items:
                    if self._is_product_type(item):
                        img_data = item.get('image')
                        if img_data:
                            if isinstance(img_data, list):
                                for img in img_data:
                                    images.extend(self._process_url(str(img), base_url, seen))
                            else:
                                images.extend(self._process_url(str(img_data), base_url, seen))
            except (json.JSONDecodeError, TypeError):
                continue
        
        return images

    def _extract_from_inline_json(self, soup: BeautifulSoup, base_url: str, seen: set) -> List[str]:
        """从内联 JSON 数据提取图片（Shopify 常用）"""
        images = []
        
        # 查找可能包含产品数据的 script 标签
        for script in soup.find_all('script'):
            text = script.string or ''
            
            # 查找 JSON 对象
            json_matches = re.findall(r'\{[^{}]*"images"[^{}]*\}', text, re.DOTALL)
            for match in json_matches:
                try:
                    # 尝试解析
                    data = json.loads(match)
                    self._extract_images_from_data(data, base_url, seen, images)
                except json.JSONDecodeError:
                    # 尝试提取 URL
                    urls = re.findall(r'https?://[^\s"\']+\.(?:jpg|jpeg|png|webp)(?:\?[^\s"\']*)?', match, re.I)
                    for url in urls:
                        images.extend(self._process_url(url, base_url, seen))
            
            # 直接查找 URL
            urls = re.findall(r'https?://[^\s"\']+\.(?:jpg|jpeg|png|webp)(?:\?[^\s"\']*)?', text, re.I)
            for url in urls[:20]:  # 限制数量
                images.extend(self._process_url(url, base_url, seen))

        return images

    def _extract_images_from_data(self, data, base_url: str, seen: set, images: list):
        """递归提取数据中的图片"""
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ('image', 'images', 'src', 'thumbnail', 'url'):
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, str):
                                images.extend(self._process_url(item, base_url, seen))
                            elif isinstance(item, dict):
                                src = item.get('src') or item.get('url')
                                if src:
                                    images.extend(self._process_url(src, base_url, seen))
                    elif isinstance(value, str):
                        images.extend(self._process_url(value, base_url, seen))
                elif isinstance(value, (dict, list)):
                    self._extract_images_from_data(value, base_url, seen, images)
        elif isinstance(data, list):
            for item in data:
                self._extract_images_from_data(item, base_url, seen, images)

    def _process_url(self, url: str, base_url: str, seen_filenames: set) -> List[str]:
        """处理图片 URL"""
        if not url or not isinstance(url, str):
            return []
        
        # 处理相对 URL
        if url.startswith('//'):
            url = 'https:' + url
        elif url.startswith('/'):
            parsed = urlparse(base_url)
            url = f"{parsed.scheme}://{parsed.netloc}{url}"
        
        if not self._is_valid_image(url):
            return []
        
        # 提取文件名用于去重
        filename = self._extract_filename(url)
        if not filename:
            return []
        
        # 基于文件名去重（不同尺寸的同一图片都会被收集）
        if filename in seen_filenames:
            return []
        
        seen_filenames.add(filename)
        return [url]

    def _is_valid_image(self, url: str) -> bool:
        """验证图片 URL"""
        if not url:
            return False
        
        url_lower = url.lower()
        
        # 首先检查是否是内部 URL（这些必须被排除）
        internal_patterns = [
            '/api/sandbox/',      # 沙箱内部代理
            '/api/proxy/',        # 代理 URL
            'code.coze.cn',       # Coze 内部域名
            'localhost',
            '127.0.0.1',
            '.coze.cn/',
        ]
        for pattern in internal_patterns:
            if pattern in url_lower:
                logger.warning(f"排除内部 URL: {url[:60]}...")
                return False
        
        # 排除视频和 GIF
        for ext in self.EXCLUDED_EXTENSIONS:
            if ext in url_lower:
                return False
        
        if '/video/' in url_lower:
            return False
        
        # 排除无效图片类型（YouTube/视频缩略图等）
        invalid_patterns = ['hqdefault', 'mqdefault', 'sddefault', 'maxresdefault', 'thumbnail_', 'preview_ima']
        for pattern in invalid_patterns:
            if pattern in url_lower:
                logger.info(f"排除无效图片类型: {url[:60]}...")
                return False
        
        # 排除所有缩略图尺寸后缀
        thumbnail_suffixes = [
            '_compact', '_small', '_thumb', '_thumbnail',
            '_pico', '_icon', '_grande', '_large',
            '_medium', '_300', '_150', '_100', '_80',
        ]
        for suffix in thumbnail_suffixes:
            if suffix in url_lower:
                logger.info(f"排除缩略图 URL: {url[:60]}...")
                return False
        
        # 排除文件名过短或不规范的图片
        filename = url_lower.split('/')[-1].split('?')[0]
        # 移除扩展名后的纯文件名
        name_without_ext = filename.rsplit('.', 1)[0] if '.' in filename else filename
        if len(name_without_ext) < 6:  # 太短的文件名可能是编码/混淆的
            logger.info(f"排除短文件名: {url[:60]}...")
            return False
        
        # 必须匹配外部图片域名（Shopify CDN 或已知图片托管服务）
        allowed_domains = [
            'cdn.shopify.com',      # Shopify
            'shopifycdn.com',       # Shopify CDN
            'amazonaws.com',        # AWS S3
            'cloudinary.com',       # Cloudinary
            'imgix.net',            # Imgix
            'unsplash.com',         # Unsplash
            'pexels.com',           # Pexels
            'shopify.com',          # Shopify 域名
            'myshopify.com',        # Shopify 子域名
        ]
        
        is_allowed_domain = any(domain in url_lower for domain in allowed_domains)
        
        # 或者是明显的外部图片 URL（有完整域名和扩展名）
        # 匹配如 https://example.com/image.jpg 这样的 URL
        is_external_full_url = (
            url_lower.startswith('http') and 
            any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.webp']) and
            not any(skip in url_lower for skip in ['/api/', '/proxy/', 'assets/'])
        )
        
        if not (is_allowed_domain or is_external_full_url):
            logger.warning(f"排除非外部图片 URL: {url[:60]}...")
            return False
        
        return True


def scrape_product(url: str, timeout: int = 20) -> Dict:
    """便捷函数"""
    scraper = ProductScraper(timeout=timeout)
    return scraper.scrape(url)
