"""
制造业AI模块 - 独立可复用模块集合

功能：
- OCR: 图片/PDF OCR 识别
- RAG: 向量检索知识库
- LLM: 大语言模型调用
- Quote: 报价引擎

使用示例：
    from app.modules import ocr_image, RAGPipeline, LLMClient, QuoteEngine

    # OCR
    result = ocr_image("blueprint.png", language="en")

    # RAG
    pipeline = RAGPipeline(collection_name="factory_kb")
    chunks = pipeline.chunk_text("长文本...")

    # LLM
    client = LLMClient()
    response = client.generate("你好")

    # Quote
    engine = QuoteEngine()
    quote = engine.generate_ai_quote("图纸文本...")
"""

from .ocr_module import ocr_image, OCRResult, check_ocr_available, ocr_pdf_page, preprocess_for_cad
from .rag_module import RAGPipeline, MANUFACTURING_TEMPLATES, get_template_kb, Chunk, SearchResult
from .llm_module import LLMClient, LLMConfig, analyze_blueprint_llm, generate_quote_description, BLUEPRINT_SYSTEM_PROMPT
from .quote_module import (
    calculate_cost,
    classify_process,
    estimate_hours,
    generate_quote,
    QuoteEngine,
    QuoteResult,
    ProcessStepData
)

__all__ = [
    # OCR
    "ocr_image",
    "OCRResult",
    "check_ocr_available",
    "ocr_pdf_page",
    "preprocess_for_cad",
    # RAG
    "RAGPipeline",
    "MANUFACTURING_TEMPLATES",
    "get_template_kb",
    "Chunk",
    "SearchResult",
    # LLM
    "LLMClient",
    "LLMConfig",
    "analyze_blueprint_llm",
    "generate_quote_description",
    "BLUEPRINT_SYSTEM_PROMPT",
    # Quote
    "calculate_cost",
    "classify_process",
    "estimate_hours",
    "generate_quote",
    "QuoteEngine",
    "QuoteResult",
    "ProcessStepData",
]
