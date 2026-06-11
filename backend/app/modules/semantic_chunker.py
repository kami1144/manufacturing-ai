"""
Semantic Chunker - 按 heading/table 结构做语义分块

功能：
- 用正则识别 # ## 标题行，保留 heading 层级
- 识别 |表格| 行，整表作为独立 chunk
- 在标题边界切分，不是500字符处切
- 每个 chunk 带 metadata: {heading_path, has_table, section_level}
- chunk 后调用 embedding_module 做向量
- 失败时降级到固定分块

依赖：
- embedding_module (../modules/embedding_module.py)
- re, typing
"""

import re
import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── 常量 ─────────────────────────────────────────────

# 最大固定分块大小（fallback 用）
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50

# 标题行正则
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$")
# 表格行正则（Markdown 表格）
TABLE_ROW_PATTERN = re.compile(r"^\|.+\|$")
# 表格分隔行（如 |---| ---|）
TABLE_SEPARATOR_PATTERN = re.compile(r"^\|[\s\-:|]+\|$")


# ── 数据结构 ─────────────────────────────────────────────

@dataclass
class Chunk:
    """单个语义分块"""
    content: str
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if "heading_path" not in self.metadata:
            self.metadata["heading_path"] = []
        if "has_table" not in self.metadata:
            self.metadata["has_table"] = False
        if "section_level" not in self.metadata:
            self.metadata["section_level"] = 0


@dataclass
class Heading:
    """标题节点"""
    level: int          # # 的数量，1-6
    text: str           # 标题文字
    line_number: int    # 在原文中的行号（从0开始）


# ── 核心类 ─────────────────────────────────────────────

class SemanticChunker:
    """
    语义分块器

    支持两种分块策略：
    1. 按 heading/table 结构语义切分（默认）
    2. 固定大小分块（降级 fallback）
    """

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    # ── Public API ─────────────────────────────────────────

    async def chunk(self, text: str) -> List[Chunk]:
        """
        主入口：将文本按语义结构分块

        Args:
            text: 原始 Markdown 文本

        Returns:
            List[Chunk]: 分块列表，每个 chunk 包含 content 和 metadata
        """
        if not text or not text.strip():
            return []

        try:
            return await self._semantic_chunk(text)
        except Exception as e:
            logger.warning(f"[SemanticChunker] 语义分块失败，降级到固定分块: {e}")
            return self._fallback_chunk(text)

    async def chunk_with_embeddings(self, text: str) -> Tuple[List[Chunk], List[List[float]]]:
        """
        分块并生成向量

        Args:
            text: 原始 Markdown 文本

        Returns:
            (chunks, embeddings): 分块列表和对应的向量列表
        """
        chunks = await self.chunk(text)

        if not chunks:
            return [], []

        # 调用 embedding_module 生成向量
        try:
            from .embedding_module import embed_texts
            texts = [c.content for c in chunks]
            import numpy as np
            embeddings = embed_texts(texts)
            # 转为 list 方便序列化
            embedding_list = embeddings.tolist() if hasattr(embeddings, 'tolist') else embeddings
            return chunks, embedding_list
        except Exception as e:
            logger.error(f"[SemanticChunker] 生成 embedding 失败: {e}")
            # 返回空向量，chunks 仍然返回
            return chunks, []

    # ── 语义分块核心 ─────────────────────────────────────────

    async def _semantic_chunk(self, text: str) -> List[Chunk]:
        """按 heading/table 结构做语义分块"""
        lines = text.split("\n")
        chunks: List[Chunk] = []

        # 1. 解析标题结构
        headings = self._parse_headings(lines)

        # 2. 解析表格结构
        tables = self._parse_tables(lines)

        # 3. 按标题段落切分
        sections = self._split_by_headings(lines, headings)

        # 4. 为每个 section 生成 chunk
        for section in sections:
            section_lines, heading_info = section
            chunk = self._create_chunk(section_lines, heading_info, tables)
            if chunk:
                chunks.append(chunk)

        # 5. 如果没有任何有效 chunk，降级到固定分块
        if not chunks:
            logger.warning("[SemanticChunker] 未产生有效 chunk，使用固定分块")
            return self._fallback_chunk(text)

        return chunks

    def _parse_headings(self, lines: List[str]) -> List[Heading]:
        """解析所有标题行"""
        headings = []
        for i, line in enumerate(lines):
            match = HEADING_PATTERN.match(line)
            if match:
                headings.append(Heading(
                    level=len(match.group(1)),
                    text=match.group(2).strip(),
                    line_number=i,
                ))
        return headings

    def _parse_tables(self, lines: List[str]) -> List[Tuple[int, int]]:
        """
        解析表格，返回表格所在行范围
        返回: [(start_line, end_line), ...]
        """
        tables = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # 检查是否是表格开始（表头行）
            if TABLE_ROW_PATTERN.match(line):
                start = i
                # 跳过表头和分隔行
                i += 1
                while i < len(lines) and TABLE_SEPARATOR_PATTERN.match(lines[i]):
                    i += 1
                # 继续读取表格数据行
                while i < len(lines) and TABLE_ROW_PATTERN.match(lines[i]):
                    i += 1
                end = i  # 不包含最后一行
                tables.append((start, end))
            else:
                i += 1
        return tables

    def _split_by_headings(
        self, lines: List[str], headings: List[Heading]
    ) -> List[Tuple[List[str], Optional[Heading]]]:
        """
        按标题边界切分文本

        Returns:
            [(section_lines, heading_info), ...]
            heading_info 为该 section 所属的标题
        """
        if not headings:
            # 没有标题，整篇文档作为一个 section
            return [(lines, None)]

        sections = []
        n = len(lines)

        for idx, heading in enumerate(headings):
            start = heading.line_number
            # 下一个标题的开始行（或文档末尾）
            end = headings[idx + 1].line_number if idx + 1 < len(headings) else n
            section_lines = lines[start:end]
            sections.append((section_lines, heading))

        return sections

    def _create_chunk(
        self,
        lines: List[str],
        heading: Optional[Heading],
        tables: List[Tuple[int, int]],
    ) -> Optional[Chunk]:
        """根据 section 创建一个 chunk"""
        if not lines:
            return None

        # 构建 heading_path
        heading_path = []
        if heading:
            heading_path = [heading.text]

        # 检查是否有表格
        has_table = self._section_has_table(lines, tables)

        # 构建 content
        content = "\n".join(lines).strip()
        if not content:
            return None

        # 判断 section_level
        section_level = heading.level if heading else 0

        return Chunk(
            content=content,
            metadata={
                "heading_path": heading_path,
                "has_table": has_table,
                "section_level": section_level,
            },
        )

    def _section_has_table(
        self, lines: List[str], tables: List[Tuple[int, int]]
    ) -> bool:
        """检查 section 是否包含表格"""
        if not tables:
            return False

        # 找到 section 的行范围
        # 简单检查：section 中是否有表格行
        for line in lines:
            if TABLE_ROW_PATTERN.match(line) and not TABLE_SEPARATOR_PATTERN.match(line):
                return True
        return False

    # ── Fallback 固定分块 ─────────────────────────────────────────

    def _fallback_chunk(self, text: str) -> List[Chunk]:
        """降级到固定大小分块"""
        chunks: List[Chunk] = []
        lines = text.split("\n")
        n = len(lines)

        if n == 0:
            return []

        start = 0
        while start < n:
            end = min(start + self.chunk_size, n)
            section_lines = lines[start:end]
            content = "\n".join(section_lines).strip()

            if content:
                chunks.append(Chunk(
                    content=content,
                    metadata={
                        "heading_path": [],
                        "has_table": False,
                        "section_level": 0,
                        "fallback": True,
                    },
                ))

            start += self.chunk_size - self.chunk_overlap

        return chunks


# ── 便捷函数 ─────────────────────────────────────────────

async def chunk_text(text: str) -> List[Chunk]:
    """简单封装"""
    chunker = SemanticChunker()
    return await chunker.chunk(text)


async def chunk_and_embed(text: str) -> Tuple[List[Chunk], List[List[float]]]:
    """分块并生成向量"""
    chunker = SemanticChunker()
    return await chunker.chunk_with_embeddings(text)


# ── 测试 ─────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    # 测试 Markdown
    test_md = """
# 产品规格书

## 1. 概述

本文档描述了 XYZ 产品的技术规格。

## 2. 材料规格

### 2.1 主要材料

| 材料 | 牌号 | 抗拉强度 | 屈服强度 |
|------|------|----------|----------|
| 不锈钢 | SUS304 | 520 MPa | 205 MPa |
| 铝合金 | AL6061 | 310 MPa | 276 MPa |

### 2.2 表面处理

- 镀锌：SECC
- 喷涂：环氧树脂

## 3. 尺寸规格

| 型号 | 长度 | 宽度 | 高度 |
|------|------|------|------|
| A1 | 100mm | 50mm | 20mm |
| A2 | 150mm | 75mm | 30mm |

### 3.1 公差要求

所有尺寸公差控制在 ±0.1mm 以内。

## 4. 包装要求

包装材料使用纸箱，内部加泡沫垫。
"""

    async def run_test():
        print("=" * 60)
        print("Semantic Chunker Test")
        print("=" * 60)

        chunker = SemanticChunker()
        chunks = await chunker.chunk(test_md)

        print(f"\n生成了 {len(chunks)} 个 chunks:\n")

        for i, chunk in enumerate(chunks, 1):
            print(f"--- Chunk {i} ---")
            print(f"Level: {chunk.metadata.get('section_level', 0)}")
            print(f"Heading Path: {' > '.join(chunk.metadata.get('heading_path', []))}")
            print(f"Has Table: {chunk.metadata.get('has_table', False)}")
            print(f"Content ({len(chunk.content)} chars):")
            print(chunk.content[:200] + ("..." if len(chunk.content) > 200 else ""))
            print()

        # 测试带 embedding
        print("=" * 60)
        print("Testing chunk_with_embeddings...")
        chunks, embeddings = await chunker.chunk_with_embeddings(test_md)
        print(f"Chunks: {len(chunks)}, Embeddings: {len(embeddings)}")
        if embeddings:
            print(f"Embedding dim: {len(embeddings[0])}")

    asyncio.run(run_test())