"""
OCR 模块 - 独立可复用

功能：
- 图片/PDF 文件 OCR 识别
- CAD 图纸预处理
- 多语言支持（日语/中文/英语）

依赖：PaddleOCR（可选，无依赖时返回错误提示）
"""

from typing import Optional, Tuple
from dataclasses import dataclass
import io
import tempfile
import os


@dataclass
class OCRResult:
    def __init__(self, text: str, confidence: float = 0.0, language: str = "auto"):
        self.text = text
        self.confidence = confidence
        self.language = language

    def to_dict(self):
        return {
            "text": self.text,
            "confidence": self.confidence,
            "language": self.language
        }


# ── 全局 OCR 单例（预加载避免每次初始化卡死）─────────────────────────

_ocr_instance = None
_ocr_lang = "en"


def _get_ocr(language: str = "en") -> "PaddleOCR":
    """获取或创建全局 OCR 实例"""
    global _ocr_instance, _ocr_lang
    if _ocr_instance is None or _ocr_lang != language:
        from paddleocr import PaddleOCR
        # PaddleOCR 3.5+ 参数：lang, use_textline_orientation
        _ocr_instance = PaddleOCR(lang=language)
        _ocr_lang = language
    return _ocr_instance


def _warmup_ocr():
    """预热 OCR（uvicorn worker 启动时调用一次，避免首次请求卡死）"""
    try:
        import logging
        logging.getLogger("paddleocr").setLevel(logging.WARNING)
        _get_ocr()
        print("[OCR] PaddleOCR pre-warmed")
    except Exception as e:
        print(f"[OCR] Warmup failed: {e}")


# 模块加载时跳过预热（uvicorn worker 启动时不要卡住）
# 改为首次使用时懒加载


def check_ocr_available() -> bool:
    """检查 OCR 是否可用"""
    try:
        _get_ocr()
        return True
    except (ImportError, Exception):
        return False


def preprocess_for_cad(image_bytes: bytes) -> bytes:
    """
    CAD 图纸预处理（简化版）
    - 灰度化
    - 二值化
    """
    try:
        import cv2
        import numpy as np

        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 灰度化
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 自适应二值化（适合CAD图纸）
        binary = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            11, 2
        )

        # 编码回 bytes
        _, buffer = cv2.imencode('.png', binary)
        return buffer.tobytes()
    except ImportError:
        return image_bytes  # 无 OpenCV 时返回原图


def ocr_image(
    image_path: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    language: str = "en",
    use_cad_mode: bool = False
) -> OCRResult:
    """
    OCR 识别主函数

    Args:
        image_path: 图片文件路径
        image_bytes: 图片字节数据
        language: 语言 ('en', 'ch', 'japan')
        use_cad_mode: 是否使用 CAD 模式（预处理）

    Returns:
        OCRResult: 识别结果

    Raises:
        RuntimeError: OCR 库不可用时
    """
    ocr = _get_ocr(language)

    # 处理 CAD 模式
    processed_bytes = image_bytes
    if use_cad_mode and image_bytes:
        processed_bytes = preprocess_for_cad(image_bytes)

    # 确定输入
    if image_path:
        result = ocr.ocr(image_path)
    elif processed_bytes:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(processed_bytes)
            temp_path = f.name
        try:
            result = ocr.ocr(temp_path)
        finally:
            os.unlink(temp_path)
    else:
        raise ValueError("Either image_path or image_bytes must be provided")

    # 解析结果
    if not result:
        return OCRResult(text="", confidence=0.0, language=language)

    # PaddleOCR v5 返回格式: [OCRResult字典, ...]
    # OCRResult 包含 keys: rec_texts, rec_scores, dt_polys 等
    ocr_result = result[0]

    # 兼容处理：可能是旧格式 list 或新格式 dict
    if isinstance(ocr_result, list):
        # 旧格式: [[bbox, (text, confidence)], ...]
        full_text = []
        total_conf = 0.0
        count = 0
        for line in ocr_result:
            if line:
                _, (text, conf) = line
                full_text.append(text)
                total_conf += conf
                count += 1
        avg_conf = total_conf / count if count > 0 else 0.0
    elif isinstance(ocr_result, dict):
        # 新格式 v5: {rec_texts: [...], rec_scores: [...]}
        rec_texts = ocr_result.get("rec_texts", [])
        rec_scores = ocr_result.get("rec_scores", [])
        full_text = rec_texts
        avg_conf = sum(rec_scores) / len(rec_scores) if rec_scores else 0.0
    else:
        return OCRResult(text="", confidence=0.0, language=language)

    return OCRResult(
        text="\n".join(full_text),
        confidence=avg_conf,
        language=language
    )


def ocr_pdf_page(
    pdf_bytes: bytes,
    page_number: int = 0,
    dpi: int = 200,
    language: str = "en"
) -> OCRResult:
    """
    PDF 单页 OCR

    Args:
        pdf_bytes: PDF 字节数据
        page_number: 页码（从0开始）
        dpi: 输出图片分辨率
        language: OCR 语言

    Returns:
        OCRResult
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise RuntimeError("PyMuPDF required for PDF OCR. Install with: pip install pymupdf")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if page_number >= len(doc):
        raise ValueError(f"Page {page_number} out of range (PDF has {len(doc)} pages)")

    page = doc[page_number]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")

    doc.close()

    return ocr_image(image_bytes=img_bytes, language=language)


# ── CLI 入口 ────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m app.modules.ocr_module <image_path>")
        sys.exit(1)

    path = sys.argv[1]
    print(f"OCR on {path}...")

    try:
        result = ocr_image(image_path=path, language="en")
        print(f"Text:\n{result.text}")
        print(f"Confidence: {result.confidence:.2f}")
    except RuntimeError as e:
        print(f"Error: {e}")
