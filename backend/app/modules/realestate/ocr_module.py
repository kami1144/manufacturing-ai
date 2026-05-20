"""
OCR 模块 - PDF/图片房源信息提取

功能：
- 从 PDF 或图片中提取房源信息
- 提取字段：地址、面积、价格、利回り、管理费、修缮费

依赖：
- pdf2image (PDF 转图片)
- pytesseract (OCR)
"""

import io
import re
from typing import Optional, Dict

# 注意：实际使用时需要安装依赖
# pip install pdf2image pytesseract pillow


def extract_property_info(content: bytes) -> Optional[Dict]:
    """
    从 PDF 或图片内容中提取房源信息

    Args:
        content: 文件内容（bytes）

    Returns:
        提取的信息字典，或 None
    """
    try:
        # 检测文件类型
        if content[:4] == b"%PDF":
            return _extract_from_pdf(content)
        elif content[:2] in [b"\xff\xd8", b"\x89\x50"]:
            return _extract_from_image(content)
        else:
            return None
    except Exception as e:
        print(f"[WARN] OCR extraction failed: {e}")
        return None


def _extract_from_pdf(content: bytes) -> Optional[Dict]:
    """
    从 PDF 提取信息（通过 pdf2image + pytesseract）
    """
    try:
        from pdf2image import convert_from_bytes
        import pytesseract

        # PDF 转图片
        images = convert_from_bytes(content, first_page=1, last_page=1)
        if not images:
            return None

        # OCR 提取
        text = pytesseract.image_to_string(images[0], lang="jpn+eng")
        return _parse_property_text(text)
    except ImportError:
        print("[WARN] pdf2image/pytesseract not installed")
        return None
    except Exception as e:
        print(f"[WARN] PDF extraction failed: {e}")
        return None


def _extract_from_image(content: bytes) -> Optional[Dict]:
    """
    从图片提取信息
    """
    try:
        import pytesseract
        from PIL import Image

        # 加载图片
        image = Image.open(io.BytesIO(content))

        # OCR 提取
        text = pytesseract.image_to_string(image, lang="jpn+eng")
        return _parse_property_text(text)
    except ImportError:
        print("[WARN] pytesseract not installed")
        return None
    except Exception as e:
        print(f"[WARN] Image extraction failed: {e}")
        return None


def _parse_property_text(text: str) -> Optional[Dict]:
    """
    解析 OCR 文本，提取房源信息
    """
    info = {}

    # 地址
    address_patterns = [
        r"住所[：:]\s*(.+?)(?:\n|$)",
        r"東京都(.+?市|.+)",
        r"大阪府(.+?市|.+)",
    ]
    for pattern in address_patterns:
        match = re.search(pattern, text)
        if match:
            info["address"] = match.group(0).strip()
            break

    # 面积
    area_patterns = [
        r"面積[：:]\s*([0-9.]+)\s*(?:m²|坪|㎡)",
        r"([0-9.]+)\s*(?:m²|坪|㎡)",
    ]
    for pattern in area_patterns:
        match = re.search(pattern, text)
        if match:
            info["area"] = match.group(1).strip()
            break

    # 价格
    price_patterns = [
        r"価格[：:]\s*([0-9,]+)\s*(?:万円|円)",
        r"([0-9,]+)\s*万円",
    ]
    for pattern in price_patterns:
        match = re.search(pattern, text)
        if match:
            info["price"] = match.group(1).strip()
            break

    # 利回り
    yield_patterns = [
        r"利回り[：:]\s*([0-9.]+)%",
        r"([0-9.]+)%\s*(?:利回り|回报)",
    ]
    for pattern in yield_patterns:
        match = re.search(pattern, text)
        if match:
            info["yield"] = match.group(1).strip() + "%"
            break

    # 管理费
    mgmt_patterns = [
        r"管理費[：:]\s*([0-9,]+)\s*(?:円|月)",
    ]
    for pattern in mgmt_patterns:
        match = re.search(pattern, text)
        if match:
            info["management_fee"] = match.group(1).strip()
            break

    # 修缮费
    repair_patterns = [
        r"修缮費[：:]\s*([0-9,]+)\s*(?:円|月)",
        r"修缮积立金[：:]\s*([0-9,]+)\s*(?:円|月)",
    ]
    for pattern in repair_patterns:
        match = re.search(pattern, text)
        if match:
            info["repair_cost"] = match.group(1).strip()
            break

    return info if info else None


def extract_from_url(url: str) -> Optional[Dict]:
    """
    从 URL 下载并提取

    Args:
        url: 文件 URL

    Returns:
        提取的信息字典
    """
    try:
        import httpx

        response = httpx.get(url, timeout=30.0)
        response.raise_for_status()

        return extract_property_info(response.content)
    except Exception as e:
        print(f"[WARN] URL extraction failed: {e}")
        return None


# 简单文本提取（无 OCR 库时的备选方案）
def extract_from_text(text: str) -> Optional[Dict]:
    """
    从文本提取房源信息（不需要 OCR）

    Args:
        text: 文本内容

    Returns:
        提取的信息字典
    """
    return _parse_property_text(text)