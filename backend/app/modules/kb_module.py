"""
知识库模块 - 制造业资料存储与检索

功能：
- 文档存储（内存，生产用 Redis/向量数据库）
- 全文检索
- 关键词匹配

简单实现：内存 + 关键词匹配
"""

from dataclasses import dataclass, field
from typing import Optional
import os
import uuid
import re
import numpy as np


@dataclass
class KBEntry:
    id: str
    title: str
    content: str
    category: str  # material/process/surface/tolerance/product/other
    keywords: list[str] = field(default_factory=list)
    source: str = ""  # 文件名或来源
    metadata: dict = field(default_factory=dict)  # 新增：结构化元数据


class KnowledgeBase:
    """制造业知识库

    支持两种搜索模式：
    - keyword_search() — 关键词匹配（原有）
    - vector_search() — 语义向量搜索（新增，需要 Embedding 模型）
    """

    def __init__(self):
        self._entries: dict[str, KBEntry] = {}
        self._embeddings: dict[str, np.ndarray] = {}  # entry_id → 向量
        self._embedding_loaded: bool = False  # True if at least one embedding succeeded
        self._failed_embeddings: set[str] = set()  # Track failed entry IDs separately

    def add(self, title: str, content: str, category: str, keywords: list[str] = None, source: str = "", metadata: dict = None) -> str:
        """添加知识条目（自动生成向量）

        Args:
            title: 标题
            content: 内容
            category: 分类
            keywords: 关键词列表
            source: 来源
            metadata: 结构化元数据（可选，包含 heading_path, section_type, has_table, level 等）
        """
        entry_id = str(uuid.uuid4())
        if keywords is None:
            keywords = self._extract_keywords(title + " " + content)
        entry = KBEntry(
            id=entry_id,
            title=title,
            content=content,
            category=category,
            keywords=keywords,
            source=source,
            metadata=metadata or {}
        )
        self._entries[entry_id] = entry
        # 自动生成向量
        self._embed_entry(entry_id)
        return entry_id

    def _embed_entry(self, entry_id: str) -> None:
        """为单个条目生成向量（轻量实现：跳过 embedding，直接记录）"""
        # 当前 embedding_module 依赖 Ollama/MiniMax API（可能不可用）
        # 知识库检索主要依赖 LLM reasoning，embedding 降级为 keyword fallback
        # 如果未来需要向量搜索，再启用 embedding
        self._embedding_loaded = False
        self._failed_embeddings.add(entry_id)
        return  # 直接返回，不阻塞 KB 加载

    def embed_all(self) -> int:
        """为所有已有条目批量生成向量（首次加载时调用）"""
        count = 0
        for entry_id in self._entries:
            if entry_id not in self._embeddings:
                self._embed_entry(entry_id)
                count += 1
        return count

    def vector_search(self, query: str, top_k: int = 5, category: str = None) -> list[dict]:
        """向量语义搜索

        Args:
            query: 查询文本
            top_k: 返回数量
            category: 可选，限定分类

        Returns:
            [{"title", "content", "category", "score", "source"}, ...]
        """
        try:
            from app.modules.embedding_module import embed_text, cosine_similarity
        except ImportError:
            print("[WARN] embedding_module not available, falling back to keyword search")
            return self.search(query, top_k, category)

        if not self._embeddings:
            self.embed_all()

        if not self._embeddings:
            # Embedding failed (API key missing etc.) — fall back to keyword search
            return self.search(query, top_k, category)

        query_emb = embed_text(query)
        texts = []
        emb_matrix = []
        entry_ids = []

        for entry_id, entry in self._entries.items():
            if category and entry.category != category:
                continue
            if entry_id not in self._embeddings:
                continue
            # Skip entries that previously failed embedding
            if entry_id in self._failed_embeddings:
                continue
            texts.append(entry.title)
            emb_matrix.append(self._embeddings[entry_id])
            entry_ids.append(entry_id)

        if not emb_matrix:
            return []

        emb_matrix = np.array(emb_matrix)
        scores = np.dot(emb_matrix, query_emb).tolist()

        results = []
        for idx, score in enumerate(scores):
            entry_id = entry_ids[idx]
            entry = self._entries[entry_id]
            results.append({
                "title": entry.title,
                "content": entry.content,
                "category": entry.category,
                "source": entry.source,
                "score": float(score),
                "metadata": entry.metadata,  # 返回 metadata
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def search(self, query: str, top_k: int = 5, category: str = None) -> list[dict]:
        """检索知识库（关键词模式，兼容旧逻辑）"""
        import re
        query_lower = query.lower().strip()
        clean_pattern = re.compile(r'[^\w\u4e00-\u9fff]+')
        query_clean = clean_pattern.sub('', query_lower)

        scored = []
        for entry in self._entries.values():
            if category and entry.category != category:
                continue

            # 计算相关性得分
            score = 0.0
            title_lower = entry.title.lower()
            content_lower = entry.content.lower()

            # 1. 完整词组在标题中（最高权重）
            if query_lower in title_lower:
                score += 30
            # 2. 完整词组在内容中
            if query_lower in content_lower:
                score += 15

            # 3. 关键词匹配（用 keywords 列表）
            for kw in entry.keywords:
                if kw.lower() in query_lower:
                    score += 10
                elif query_lower in kw.lower():
                    score += 8

            # 4. 字符级重叠（query 中每个字符是否出现在 title/content 中）
            # 适用于混合查询如 "SUS304材质"
            q_chars = set(query_clean)
            # 标题字符覆盖率
            title_chars = set(re.sub(r'[^\w\u4e00-\u9fff]', '', title_lower))
            char_overlap = len(q_chars & title_chars) / max(len(q_chars), 1)
            score += char_overlap * 5

            # 5. 内容字符覆盖率
            content_chars = set(re.sub(r'[^\w\u4e00-\u9fff]', '', content_lower))
            content_overlap = len(q_chars & content_chars) / max(len(q_chars), 1)
            score += content_overlap * 2

            if score > 0:
                scored.append({
                    "title": entry.title,
                    "content": entry.content,
                    "category": entry.category,
                    "score": score,
                    "metadata": entry.metadata,  # 返回 metadata
                })

        # 排序返回
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def _extract_keywords(self, text: str) -> list[str]:
        """从文本中提取关键词（简单实现）"""
        # 移除常见停用词
        stopwords = {
            "的", "是", "在", "和", "与", "或", "及", "等", "该", "为",
            "a", "an", "the", "is", "are", "was", "were", "and", "or", "in", "on", "at",
            "to", "for", "of", "with", "by", "from", "as"
        }
        words_pattern = re.compile(r'[\w\u4e00-\u9fff]+')
        keywords = [w for w in words_pattern.findall(text.lower()) if len(w) >= 2 and w not in stopwords]
        # 去重保留出现次数多的
        from collections import Counter
        counts = Counter(keywords)
        return [w for w, c in counts.most_common(20)]

    def count(self) -> int:
        return len(self._entries)

    def clear(self):
        self._entries.clear()


# ── 全局知识库实例 ─────────────────────────────────────────

_kb: Optional[KnowledgeBase] = None


def get_kb() -> KnowledgeBase:
    """获取全局知识库，先尝试从持久化加载，失败则回退到内存"""
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
        _load_from_persistence(_kb)  # 尝试从 SQLite 加载
        if _kb.count() == 0:
            load_mock_data()  # 首次启动，加载 mock 数据
            _save_to_persistence(_kb)  # 保存到持久化
        else:
            # 已从 SQLite 加载，但强制重新同步 desktop 文档（保证最新）
            _reload_factory_docs()
    return _kb


def _load_from_persistence(kb: KnowledgeBase) -> int:
    """从 SQLite 加载已保存的知识条目"""
    try:
        from app.workflow.kb_persistence import get_persisted_kb
        persisted = get_persisted_kb()
        entries = persisted.load_all()

        for pe in entries:
            kb._entries[pe.id] = KBEntry(
                id=pe.id,
                title=pe.title,
                content=pe.content,
                category=pe.category,
                keywords=pe.keywords,
                source=pe.source
            )
        return len(entries)
    except Exception as e:
        print(f"[WARN] KB persistence load failed: {e}")
        return 0


def _save_to_persistence(kb: KnowledgeBase) -> int:
    """将所有 KB 条目保存到 SQLite"""
    try:
        from app.workflow.kb_persistence import get_persisted_kb
        persisted = get_persisted_kb()
        for entry in kb._entries.values():
            persisted.save_entry(entry)
        return kb.count()
    except Exception as e:
        print(f"[WARN] KB persistence save failed: {e}")
        return 0


def load_mock_data():
    """加载模拟工厂数据（用于测试）"""
    kb = get_kb()

    # ── 桌面工厂测试文档 ──────────────────────────────────────────────
    # 从 ~/Desktop/factory-test-docs/ 加载 50 条真实工厂文档
    factory_docs_dir = os.path.join(os.path.expanduser("~"), "Desktop", "factory-test-docs")
    if os.path.isdir(factory_docs_dir):
        _load_factory_docs(kb, factory_docs_dir)
    # ─────────────────────────────────────────────────────────────────────

    # 材质类
    kb.add(
        title="SUS304不锈钢材质规格",
        content="""SUS304 (18/8不锈钢)
化学成分: C≤0.08%, Si≤1.00%, Mn≤2.00%, P≤0.045%, S≤0.030%, Cr 18.0-20.0%, Ni 8.0-10.5%
对应标准: JIS G4303, ASTM A240, GB/T 3280
抗拉强度: ≥520 MPa | 屈服强度: ≥205 MPa | 延伸率: ≥40% | 硬度: ≤201 HB
密度: 8.00 g/cm³ | 热膨胀系数: 17.3×10⁻⁶/°C | 热导率: 16.3 W/(m·K)
焊接性能优良，适合各种焊接方法
适用: 精密机械零部件、食品加工设备、医疗器械配件
表面处理: 抛光、电镀、喷涂、化学钝化""",
        category="material",
        keywords=["SUS304", "不锈钢", "18/8", "304", "材质", "钢材", "铬镍钢"],
        source="SUS304材质规格书.md"
    )

    kb.add(
        title="AL5052铝合金材质规格",
        content="""AL5052 (Al-Mg系铝合金)
化学成分: Mg 2.2-2.8%, Cr 0.15-0.35%, Si≤0.25%, Fe≤0.40%
对应标准: JIS H4000, ASTM B209
抗拉强度: 193-269 MPa | 屈服强度: ≥65 MPa | 延伸率: ≥25%
密度: 2.68 g/cm³ | 热膨胀系数: 23.8×10⁻⁶/°C | 热导率: 138 W/(m·K)
折弯性能良好，折弯半径建议≥0.8倍板厚
阳极氧化效果优良
适用: 电子设备外壳、车辆装饰件、船舶内饰、油箱及管路""",
        category="material",
        keywords=["AL5052", "铝合金", "5052", "Al-Mg", "材质", "铝材"],
        source="AL5052铝合金规格书.md"
    )

    kb.add(
        title="SECC镀锌钢板材质规格",
        content="""SECC (电镀锌钢板)
基板: SPCC冷轧钢 | 镀层: 锌电镀 | 标准: JIS G3313
镀锌量: 20-60 g/m² (双面) | 镀层厚度: 约3-9μm
抗拉强度: 270-330 MPa | 屈服强度: 180-280 MPa | 延伸率: 26-40%
适用: 电子设备外壳(IT产品)、仪表壳体、家具五金配件、汽车内饰件
注意: 折弯时镀层可能龟裂，建议折弯线与轧制方向垂直""",
        category="material",
        keywords=["SECC", "镀锌钢板", "镀锌", "SPCC", "电镀锌", "钢板", "材质"],
        source="SECC镀锌钢板规格书.md"
    )

    # 工艺类
    kb.add(
        title="CNC铣削加工工艺标准",
        content="""CNC铣削加工工艺
适用范围: 立方体类、板类零件3轴CNC铣削加工
设备精度: ±0.02mm | 表面粗糙度: Ra 1.6μm

工艺流程:
1. 来料检验(IQC): 核对材质报告、检查尺寸、外观检查
2. 编程: 根据CAD图纸制作加工程序
3. 装夹: 使用百分表找正
4. 粗加工: 切深1-3mm, 进给800-1500mm/min, 留余量0.3-0.5mm
5. 半精加工: 切深0.5-1mm, 进给500-800mm/min
6. 精加工: 切深0.1-0.3mm, 进给200-500mm/min, Ra1.6
7. 去毛刺: 手工去毛刺
8. 全检(QC): 尺寸全检
9. 出货: 清洗防锈+包装

常见问题: 振刀(降低转速), 粘刀(使用冷却液), 尺寸超差(修正刀补)""",
        category="process",
        keywords=["CNC", "铣削", "加工工艺", "数控", "切削", "刀具", "粗加工", "精加工"],
        source="CNC铣削加工工艺标准.md"
    )

    kb.add(
        title="钣金加工工艺标准",
        content="""钣金加工工艺
适用范围: 1.0-3.0mm厚度板材钣金加工
设备: 激光切割机、数控折弯机、焊接设备、表面处理设备

工艺流程:
1. 来料检验(IQC): 确认材质/板厚, 检查表面质量
2. 激光切割: 氮气辅助切割, 切口垂直度误差≤0.1mm
3. 折弯: 最小折弯半径=板厚×1.0, 角度公差±1°
4. 焊接: 氩弧焊(TIG)/点焊, 焊后打磨
5. 表面处理: 脱脂清洗→防锈→喷粉/喷漆/电泳
6. 检验: 尺寸+外观+功能

常用材料: SECC, SPCC, AL5052, SUS304
线性尺寸公差: ±0.2mm | 角度: ±1° | 折弯高度: ±0.3mm""",
        category="process",
        keywords=["钣金", "折弯", "激光切割", "焊接", "冲压", "板材", "工艺"],
        source="钣金加工工艺标准.md"
    )

    kb.add(
        title="表面处理工艺标准",
        content="""表面处理工艺

1. 电镀(镀镍/镀铬):
   前处理(脱脂→酸洗→活化)→镀镍(3-8μm)→镀铬(0.3-1μm)
   盐雾试验≥24小时 | 适用: 外观件, 耐磨件, 防锈件

2. 粉末喷涂:
   前处理(脱脂→磷化)→静电喷涂→高温固化(180-200°C, 15-20min)
   膜厚60-120μm, 附着力0级, 耐冲击≥50kg·cm
   适用: 电子设备外壳, 家具五金, 户外设施

3. 阳极氧化(铝合金专用):
   硫酸法阳极氧化, 膜厚10-25μm
   染色(可选): 本色/黑色/彩色
   封孔处理 | 盐雾≥72小时 | 硬度≥300HV

4. 化学钝化(不锈钢):
   硝酸钝化(15-25%, 30min)
   钝化膜厚度1-3nm, 耐腐蚀性显著提升""",
        category="surface",
        keywords=["表面处理", "电镀", "镀镍", "镀铬", "喷涂", "粉末喷涂", "阳极氧化", "钝化", "钝化处理"],
        source="表面处理工艺标准.md"
    )

    # 公差/质量类
    kb.add(
        title="公差与质量标准",
        content="""制造业公差与质量标准

线性尺寸公差 (GB/T 1804-m):
0.5-6mm: 精密级±0.05mm, 中等级±0.10mm, 粗糙级±0.20mm
6-30mm: 精密级±0.10mm, 中等级±0.20mm, 粗糙级±0.50mm
30-120mm: 精密级±0.15mm, 中等级±0.30mm, 粗糙级±0.80mm
120-400mm: 精密级±0.20mm, 中等级±0.50mm, 粗糙级±1.20mm

角度公差:
0°-10°: ±1° | 10°-45°: ±30' | 45°-90°: ±15'

形位公差: 圆度≤0.02mm | 圆柱度≤0.03mm | 平行度≤0.03mm | 垂直度≤0.02mm | 同轴度≤0.03mm

表面粗糙度Ra: 12.5(粗车)→6.3(一般装配)→3.2(回转体)→1.6(齿轮)→0.8(导柱)→0.4(精密配合)

检验规范:
- 首件检验: 尺寸全检
- 巡检: 每50件抽检5件, SPC控制
- 出货: AQL 1.0 Ⅱ级, 主要尺寸100%全检""",
        category="tolerance",
        keywords=["公差", "尺寸公差", "角度公差", "形位公差", "粗糙度", "Ra", "精度", "质量标准", "AQL", "SPC", "CPK", "检验"],
        source="公差与质量标准.md"
    )

    # 产品类
    kb.add(
        title="产品目录2024",
        content="""产品目录2024

精密机械零部件:
- A001 不锈钢精密轴套: SUS304, Φ25×Φ15×L50mm, 公差±0.01mm, 磨削Ra0.8
- A002 铝合金外壳: AL5052-H32, 200×150×30mm, 公差±0.1mm, 阳极氧化本色
- A003 不锈钢支架: SUS304, 100×80×5mm, 公差±0.05mm, 拉丝表面

钣金件:
- B001 电子设备底座: SECC 1.5mm, 300×200×50mm, 激光切割+折弯+喷粉, 黑色
- B002 不锈钢电气箱: SUS304 2.0mm, 400×300×150mm, 激光切割+折弯+焊接+钝化
- B003 铝合金面板: AL5052 2.0mm, 250×180×3mm, 激光切割+折弯+阳极氧化, 黑色

表面处理加工:
- C001 镀镍+镀铬: 镍3-8μm+铬0.5μm, 盐雾≥24h, 交期5-7天
- C002 粉末喷涂: 膜厚60-120μm, RAL色/自定义, 交期3-5天
- C003 阳极氧化: 铝合金, 膜厚10-25μm, 本色/黑色/彩色, 交期3-5天""",
        category="product",
        keywords=["产品", "目录", "零部件", "轴套", "外壳", "支架", "底座", "电气箱", "面板", "交期", "报价"],
        source="产品目录2024.md"
    )

    return kb


def _reload_factory_docs():
    """强制重新从 desktop 加载文档（覆盖已存在的同名条目）"""
    factory_docs_dir = os.path.join(os.path.expanduser("~"), "Desktop", "factory-test-docs")
    if not os.path.isdir(factory_docs_dir):
        return
    # 清除旧的 factory docs 条目（按 source 匹配 desktop 文件名）
    factory_files = set(os.path.basename(f) for f in __import__('glob').glob(os.path.join(factory_docs_dir, "*.md")))
    to_remove = [eid for eid, entry in _kb._entries.items()
                 if entry.source in factory_files]
    for eid in to_remove:
        del _kb._entries[eid]
    # 重新加载
    _load_factory_docs(_kb, factory_docs_dir)
    # 同步到 sqlite
    _save_to_persistence(_kb)
    print(f"  [KB] Reloaded {len(to_remove)} old + {len(factory_files)} new entries from desktop")


def _load_factory_docs(kb: KnowledgeBase, docs_dir: str):
    """从目录加载工厂测试文档到 KB"""
    import glob

    # 分类映射（从文件名推断）
    category_map = {
        "品質検査": "quality",
        "製造指示": "process",
        "設備メンテ": "equipment",
        "安全チェック": "safety",
        "原材料試験": "material",
        "出荷検査": "quality",
        "コスト見積": "cost",
        "原価計算": "cost",
        "プロセス改善": "improvement",
        "顧客見積": "cost",
        "工場監査": "audit",
        "生産性向上": "production",
        "納期遅延": "delivery",
        "不適合品": "quality",
        "温度管理": "other",
        "仕入先評価": "audit",
        "環境計測": "environment",
        "工程能力": "process",
        "ISO9001": "quality",
        "作業標準": "process",
        "減価償却": "equipment",
        "物流進捗": "logistics",
        "検査治具": "equipment",
        "出荷予定": "logistics",
        "廃棄物": "environment",
        "サプライチェーン": "supply",
        "試作品": "development",
        "勤怠": "hr",
        "不良解析": "process",
        "安全衛生": "safety",
        "受発注": "procurement",
        "エネルギー": "environment",
        "製造指図": "process",
        "建設工事": "construction",
        "購買": "procurement",
        "5S": "production",
        "外国人": "hr",
        "工程管理": "process",
        "機械潤滑": "equipment",
        "検査成績": "quality",
        "工場運営": "other",
    }

    pattern = os.path.join(docs_dir, "*.md")
    files = sorted(glob.glob(pattern))

    for filepath in files:
        filename = os.path.basename(filepath)
        # 跳过 QA 问答对文件
        if filename.startswith("QA_"):
            continue

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            if not content.strip():
                continue

            # 从第一行提取标题（## 标题 或 # 标题）
            title = filename.replace(".md", "")
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("# "):
                    title = line[2:].strip()
                    break

            # 推断 category
            category = "other"
            for key, cat in category_map.items():
                if key in filename:
                    category = cat
                    break

            # 提取关键词（从标题和内容中抽词）
            keywords = kb._extract_keywords(title + " " + content[:500])

            kb.add(
                title=title,
                content=content,
                category=category,
                keywords=keywords,
                source=filename,
            )
            print(f"  [KB] Loaded: {filename} ({category})")
        except Exception as e:
            print(f"  [KB] Failed to load {filepath}: {e}")

    count = len(kb._entries)
    print(f"  [KB] Total entries after factory docs: {count}")
