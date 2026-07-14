# bible_engine.py - 圣经查询引擎
"""
圣经查询引擎 - 基于 SQLite 的圣经经文查询工具

功能特性:
    - 支持多种引用格式（简称/全称，中英文标点）
    - 智能解析复杂引用（多章节、多范围、跨书卷）
    - 格式化输出（自动合并连续节号）
    - 程序化接口（返回结构化数据）
    - 关键词搜索

使用示例:
    >>> engine = BibleEngine()
    >>> 
    >>> # 格式化文本输出
    >>> print(engine.query_formatted("诗122:1—2，4-5，8"))
    诗篇122:1-2,4-5,8
        1 人对我说：“我们往耶和华的殿去。”我就欢喜。
        2 耶路撒冷啊，我们的脚站在你的门内。
        4 众支派，就是耶和华的支派，上那里去...
        5 因为在那里设立审判的宝座，就是大卫家的宝座。
        8 因我弟兄和同伴的缘故，我要说：“愿平安在你中间！”
    >>> 
    >>> # 结构化数据输出
    >>> result = engine.query("约3:16")
    >>> for verse in result.data:
    ...     print(f"{verse.book_name}{verse.chapter}:{verse.verse} {verse.text}")
    约翰福音3:16 神爱世人，甚至将他的独生子赐给他们...
    >>> 
    >>> # 关键词搜索
    >>> verses = engine.search("爱", limit=10)
    >>> 
    >>> engine.close()

支持的引用格式:
    - 单节: 约3:16
    - 范围: 诗122:1-9
    - 多范围: 太11:16-19,25-30
    - 多章节: 诗122:1-2,4-5,8,123:2
    - 跨书卷: 诗122:1-2;希伯来书10:25
    - 多种标点: ：；，、—－等自动转换

数据模型:
    Verse: 单节经文 (book_name, book_short, chapter, verse, text, testament)
    QueryResult: 查询结果 (success, data, errors, warnings, query_text)
"""

import sqlite3
import os
import re
from typing import List, Tuple, Optional, Dict, Any, Union
from dataclasses import dataclass, asdict
import json


@dataclass
class Verse:
    """
    单节经文数据类
    
    Attributes:
        book_name: 书卷全称，如 "创世记"
        book_short: 书卷简称，如 "创"
        chapter: 章号 (1-based)
        verse: 节号 (1-based)
        text: 经文内容
        testament: 所属约别，"旧约" 或 "新约"
    
    Example:
        >>> verse = Verse("约翰福音", "约", 3, 16, "神爱世人...", "新约")
        >>> print(f"{verse.book_name}{verse.chapter}:{verse.verse}")
        约翰福音3:16
    """
    book_name: str
    book_short: str
    chapter: int
    verse: int
    text: str
    testament: str
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


@dataclass
class QueryResult:
    """
    查询结果数据类
    
    Attributes:
        success: 是否成功
        data: 经文列表 (List[Verse])
        errors: 错误信息列表
        warnings: 警告信息列表
        query_text: 原始查询文本
    
    Example:
        >>> result = engine.query("约3:16")
        >>> if result.success:
        ...     print(f"找到 {len(result.data)} 节经文")
        ... else:
        ...     print(f"错误: {result.errors}")
    """
    success: bool
    data: List[Verse]
    errors: List[str]
    warnings: List[str]
    query_text: str
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'success': self.success,
            'data': [v.to_dict() for v in self.data],
            'errors': self.errors,
            'warnings': self.warnings,
            'query_text': self.query_text,
            'count': len(self.data)
        }
    
    def to_json(self, indent: int = 2) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class BibleEngine:
    """
    圣经查询引擎
    
    提供圣经经文的查询、搜索和格式化输出功能。
    
    Attributes:
        db_path: 数据库文件路径
        conn: SQLite 连接对象
        cursor: SQLite 游标对象
        short_to_full: 简称到全称的映射
        short_to_sn: 简称到书卷编号的映射
        sn_info: 书卷编号到信息的映射
        all_shorts: 所有简称列表
        patterns: 预编译的正则表达式
        _verse_cache: 节数缓存
    
    Example:
        >>> engine = BibleEngine()
        >>> result = engine.query_formatted("创1:1-3")
        >>> print(result)
        创世记1:1-3
            1 起初，神创造天地。
            2 地是空虚混沌，渊面黑暗；神的灵运行在水面上。
            3 神说：要有光，就有了光。
        >>> engine.close()
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        初始化圣经查询引擎
        
        Args:
            db_path: 数据库文件路径。如果为 None，自动在 data 目录下查找
        
        Raises:
            FileNotFoundError: 数据库文件不存在
            sqlite3.Error: 数据库连接失败
        
        Example:
            >>> # 使用默认路径
            >>> engine = BibleEngine()
            >>> 
            >>> # 指定路径
            >>> engine = BibleEngine("/path/to/bible.db")
        """
        if db_path is None:
            src_folder = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(src_folder, "data", "Bible_Simplified_Chinese_Union_Version.db")
        
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"数据库文件不存在: {db_path}")
        
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self._load_mappings()
        self._compile_patterns()
        self._verse_cache = {}
    
    def _load_mappings(self):
        """加载书卷映射（内部方法）"""
        self.cursor.execute("""
            SELECT SN, ShortName, FullName, ChapterNumber, NewOrOld 
            FROM BibleID ORDER BY SN
        """)
        books = self.cursor.fetchall() 
        
        self.short_to_full = {}
        self.short_to_sn = {}
        self.full_to_sn = {}
        self.sn_info = {}
        self.all_shorts = []
        
        for sn, short, full, chapters, testament in books:
            short = short.strip()
            full = full.strip()
            self.short_to_full[short] = full
            self.short_to_sn[short] = sn
            self.full_to_sn[full] = sn
            self.sn_info[sn] = {
                'short': short,
                'full': full,
                'chapters': chapters,
                'testament': '旧约' if testament == 0 else '新约'
            }
            self.all_shorts.append(short)
        
        # 按长度排序，优先匹配长的
        self.all_shorts.sort(key=len, reverse=True)
    
    def _compile_patterns(self):
        """预编译正则表达式（内部方法）"""
        self.patterns = {
            'range_sep': re.compile(r'[-–—]'),
            'ref_sep': re.compile(r'[;；,，、]'),  
            'cv': re.compile(r'^(\d+):(\d+)$'),
        }
    
    def _normalize(self, text: str) -> str:
        """
        标准化标点符号（内部方法）
        
        将中文标点转换为英文标点，统一格式。
        """
        if not text:
            return text
        for old, new in [('：', ':'), ('；', ';'), ('—', '-'), ('－', '-'), ('–', '-')]:
            text = text.replace(old, new)
        return ' '.join(text.split())
    
    def _extract_book(self, text: str) -> Tuple[Optional[str], str]:
        """
        从文本中提取书名（内部方法）
        
        Returns:
            (书卷简称, 剩余文本)
        """
        text = text.strip()
        for short in self.all_shorts:
            if text.startswith(short):
                return short, text[len(short):].strip()
        
        # 尝试全称
        for short, full in self.short_to_full.items():
            if text.startswith(full):
                return short, text[len(full):].strip()
        
        return None, text
    
    def _get_max_verse(self, sn: int, chapter: int) -> int:
        """
        获取某章的最大节数（内部方法，带缓存）
        
        Args:
            sn: 书卷编号
            chapter: 章号
        
        Returns:
            最大节数，如果不存在返回 0
        """
        key = f"{sn}_{chapter}"
        if key in self._verse_cache:
            return self._verse_cache[key]
        
        self.cursor.execute("""
            SELECT MAX(VerseSN) FROM Bible
            WHERE VolumeSN = ? AND ChapterSN = ?
        """, (sn, chapter))
        result = self.cursor.fetchone()
        max_v = result[0] if result and result[0] is not None else 0
        self._verse_cache[key] = max_v
        return max_v
    
    def query(self, text: str) -> QueryResult:
        """
        查询圣经经文，返回结构化数据
        
        Args:
            text: 查询文本，支持多种格式
        
        Returns:
            QueryResult: 包含查询结果和状态信息
        
        Example:
            >>> result = engine.query("创1:1-3")
            >>> for verse in result.data:
            ...     print(f"{verse.verse} {verse.text}")
            1 起初，神创造天地。
            2 地是空虚混沌...
            3 神说：要有光...
        """
        result = QueryResult(
            success=True,
            data=[],
            errors=[],
            warnings=[],
            query_text=text
        )
        
        if not text or not text.strip():
            result.success = False
            result.errors.append("查询文本为空")
            return result
        
        text = self._normalize(text)
        
        try:
            ref_result = self._query_single_ref(text)
            result.data.extend(ref_result.data)
            if not ref_result.success:
                result.success = False
                result.errors.extend(ref_result.errors)
            result.warnings.extend(ref_result.warnings)
        except Exception as e:
            result.success = False
            result.errors.append(f"查询失败: {str(e)}")
        
        return result

    def query_formatted(self, text: str) -> str:
        """
        查询圣经经文，返回格式化文本
        
        Args:
            text: 查询文本，支持多种格式
        
        Returns:
            str: 格式化的经文文本，适合直接打印显示
        
        Example:
            >>> print(engine.query_formatted("诗122:1-2,4-5"))
            诗篇122:1-2,4-5
                1 人对我说：我们往耶和华的殿去...
                2 耶路撒冷啊，我们的脚站在你的门内。
                4 众支派，就是耶和华的支派...
                5 因为在那里设立审判的宝座...
        """
        result = self.query(text)
        return self.format_result(result)
    
    def _query_single_ref(self, ref: str) -> QueryResult:
        """
        查询单个引用（内部方法）
        
        核心原则：书卷分割只看书名，不受逗号分号影响
        """
        result = QueryResult(
            success=True,
            data=[],
            errors=[],
            warnings=[],
            query_text=ref
        )
        
        if not ref or not ref.strip():
            result.success = False
            result.errors.append("查询文本为空")
            return result
        
        ref = ref.strip()
        
        # ========== 第一步：提取书名 ==========
        book_short, remaining = self._extract_book_from_text(ref)
        
        if not book_short:
            result.success = False
            result.errors.append(f"无法识别书名: {ref}")
            return result
        
        sn = self.short_to_sn[book_short]
        
        # ========== 第二步：解析剩余部分 ==========
        # 收集所有查询单元: (book_short, sn, start_ch, start_vs, end_ch, end_vs)
        units = []
        
        self._parse_remaining(
            result, book_short, sn, remaining, 
            units, current_chapter=None
        )
        
        # ========== 第三步：执行查询 ==========
        for book, sn, start_ch, start_vs, end_ch, end_vs in units:
            segments = self._split_range(sn, start_ch, start_vs, end_ch, end_vs)
            for ch, vs_start, vs_end in segments:
                self._query_single(result, book, ch, vs_start, vs_end)
        
        if result.errors and not result.data:
            result.success = False
        
        return result


    def _parse_remaining(self, result: QueryResult, book_short: str, sn: int, 
                        text: str, units: list, current_chapter: int = None):
        """
        解析书名后面的剩余部分
        
        按分号分割，每个部分独立处理
        """
        if not text or not text.strip():
            return
        
        text = text.strip()
        
        # 按分号分割（保留分隔符用于判断）
        # 使用正则保留分隔符
        semicolon_parts = re.split(r'([；;])', text)
        
        for part in semicolon_parts:
            part = part.strip()
            if not part:
                continue
            
            # 如果是分号本身，跳过（它只是分隔符标记）
            if part in ['；', ';']:
                continue
            
            # ========== 检查是否以新书名开头 ==========
            new_book, remaining = self._extract_book_from_text(part)
            
            if new_book:
                # 切换到新书卷
                new_sn = self.short_to_sn[new_book]
                # 递归解析剩余部分，重置当前章
                self._parse_remaining(
                    result, new_book, new_sn, remaining,
                    units, current_chapter=None
                )
                continue
            
            # ========== 没有新书名：解析当前书卷 ==========
            # 分号后面没有新书名 → 章号递增
            # 但注意：part 可能包含逗号
            self._parse_part(
                result, book_short, sn, part,
                units, current_chapter, is_semicolon=True
            )


    def _parse_part(self, result: QueryResult, book_short: str, sn: int,
                text: str, units: list, current_chapter: int = None,
                is_semicolon: bool = True):
        """解析一个分号片段（可能包含逗号）"""
        if not text or not text.strip():
            return
        
        text = text.strip()
        
        # 按逗号分割
        comma_parts = re.split(r'[，,]', text)
        
        i = 0
        while i < len(comma_parts):
            cp = comma_parts[i].strip()
            if not cp:
                i += 1
                continue
            
            # 检查是否以新书名开头
            new_book, remaining = self._extract_book_from_text(cp)
            
            if new_book:
                # 🔥 关键修复：合并当前及后续所有逗号片段
                rest_of_text = cp
                for j in range(i + 1, len(comma_parts)):
                    rest_of_text += "，" + comma_parts[j]
                
                new_sn = self.short_to_sn[new_book]
                self._parse_remaining(
                    result, new_book, new_sn, rest_of_text,
                    units, current_chapter=None
                )
                break  # 后面的内容已递归处理，跳出循环
            
            # 没有新书名
            if ':' in cp or '：' in cp:
                # 有冒号：正常解析
                bounds = self._parse_bounds(sn, book_short, cp, result)
                if bounds:
                    start_ch, start_vs, end_ch, end_vs = bounds
                    units.append((book_short, sn, start_ch, start_vs, end_ch, end_vs))
                    current_chapter = end_ch
                i += 1
                continue
            
            # 没有冒号
            if i == 0 and current_chapter is None:
                # 第一个片段且没有当前章：章号
                if '-' in cp or '—' in cp or '–' in cp:
                    parts = re.split(r'[-–—]', cp)
                    start_ch = int(parts[0].strip())
                    end_ch = int(parts[1].strip())
                    if start_ch > end_ch:
                        start_ch, end_ch = end_ch, start_ch
                    for ch in range(start_ch, end_ch + 1):
                        max_verse = self._get_max_verse(sn, ch)
                        units.append((book_short, sn, ch, 1, ch, max_verse))
                    current_chapter = end_ch
                else:
                    ch = int(cp)
                    max_verse = self._get_max_verse(sn, ch)
                    units.append((book_short, sn, ch, 1, ch, max_verse))
                    current_chapter = ch
                i += 1
                continue
            
            # 后续片段：同章节
            if current_chapter is None:
                result.errors.append(f"逗号分隔但当前章号未知: {cp}")
                i += 1
                continue
            
            if '-' in cp or '—' in cp or '–' in cp:
                parts = re.split(r'[-–—]', cp)
                start_vs = int(parts[0].strip())
                end_vs = int(parts[1].strip())
                if start_vs > end_vs:
                    start_vs, end_vs = end_vs, start_vs
                units.append((
                    book_short, sn,
                    current_chapter, start_vs,
                    current_chapter, end_vs
                ))
            else:
                vs = int(cp)
                units.append((
                    book_short, sn,
                    current_chapter, vs,
                    current_chapter, vs
                ))
            
            i += 1


    def _extract_book_from_text(self, text: str):
        """
        从文本开头提取书名
        
        返回: (书卷简称, 剩余部分)
        
        示例:
            "希伯来书 10:25，27" → ("希伯来书", "10:25，27")
            "约3:16" → ("约", "3:16")
            "太13:1-9，18-23" → ("太", "13:1-9，18-23")
            "18-23" → (None, "18-23")
        """
        text = text.strip()
        if not text:
            return None, text
        
        # 先尝试全称
        for short, full in self.short_to_full.items():
            if text.startswith(full):
                remaining = text[len(full):].strip()
                return short, remaining
        
        # 再尝试简称
        # 按长度从长到短排序，避免 "约翰" 被 "约" 先匹配
        sorted_shorts = sorted(self.short_to_sn.keys(), key=len, reverse=True)
        for short in sorted_shorts:
            if text.startswith(short):
                remaining = text[len(short):].strip()
                return short, remaining
        
        return None, text


    def _parse_bounds(self, sn: int, book_short: str, unit: str, result: QueryResult):
        """解析单个单元（包含冒号）"""
        unit = unit.strip()
        
        if ':' not in unit and '：' not in unit:
            result.errors.append(f"缺少冒号: {unit}")
            return None
        
        colon_pos = unit.find(':') if ':' in unit else unit.find('：')
        before = unit[:colon_pos].strip()
        after = unit[colon_pos+1:].strip()
        
        before_has_range = self._contains_range(before)
        after_has_range = self._contains_range(after)
        
        if before_has_range and after_has_range:
            return self._parse_bounds_with_dash(sn, book_short, unit, result)
        elif before_has_range:
            # 章范围 + 节限制：1-3:5
            parts = re.split(r'[-–—]', before)
            start_ch = int(parts[0].strip())
            end_ch = int(parts[1].strip())
            if start_ch > end_ch:
                start_ch, end_ch = end_ch, start_ch
            
            if after_has_range:
                after_parts = re.split(r'[-–—]', after)
                start_vs = int(after_parts[0].strip())
                end_vs = int(after_parts[1].strip())
                if start_vs > end_vs:
                    start_vs, end_vs = end_vs, start_vs
                return (start_ch, 1, end_ch, end_vs)
            else:
                end_vs = int(after)
                return (start_ch, 1, end_ch, end_vs)
        else:
            # 单章
            start_ch = int(before)
            end_ch = start_ch
            
            # 检测跨章：after 包含冒号
            if ':' in after or '：' in after:
                return self._parse_bounds_with_dash(sn, book_short, unit, result)
            
            if after_has_range:
                after_parts = re.split(r'[-–—]', after)
                start_vs = int(after_parts[0].strip())
                end_vs = int(after_parts[1].strip())
                if start_vs > end_vs:
                    start_vs, end_vs = end_vs, start_vs
                return (start_ch, start_vs, end_ch, end_vs)
            else:
                vs = int(after)
                return (start_ch, vs, end_ch, vs)


    def _contains_range(self, text: str) -> bool:
        """检测文本是否包含范围符号"""
        if not text:
            return False
        return any(ch in text for ch in ['-', '—', '–'])


    def _parse_bounds_with_dash(self, sn: int, book_short: str, unit: str, result: QueryResult):
        """
        解析跨章连续范围：2:3-3:16
        """
        # 找到第一个 - 的位置
        dash_pos = -1
        for ch in ['-', '—', '–']:
            pos = unit.find(ch)
            if pos != -1:
                dash_pos = pos
                break
        
        if dash_pos == -1:
            result.errors.append(f"无法解析范围: {unit}")
            return None
        
        left = unit[:dash_pos].strip()
        right = unit[dash_pos+1:].strip()
        
        left_bounds = self._parse_single_point(sn, book_short, left, result)
        if not left_bounds:
            return None
        
        right_bounds = self._parse_single_point(sn, book_short, right, result)
        if not right_bounds:
            return None
        
        start_ch, start_vs = left_bounds
        end_ch, end_vs = right_bounds
        
        if start_ch > end_ch or (start_ch == end_ch and start_vs > end_vs):
            result.errors.append(f"无效范围（起点 > 终点）: {unit}")
            return None
        
        return (start_ch, start_vs, end_ch, end_vs)


    def _parse_single_point(self, sn: int, book_short: str, text: str, result: QueryResult):
        """
        解析单个位置点，返回 (章, 节)
        
        支持：
            - 3:16 → (3, 16)
            - 3 → (3, 1)
        """
        text = text.strip()
        
        if ':' in text or '：' in text:
            colon_pos = text.find(':') if ':' in text else text.find('：')
            before = text[:colon_pos].strip()
            after = text[colon_pos+1:].strip()
            ch = int(before)
            vs = int(after)
            return (ch, vs)
        else:
            ch = int(text)
            return (ch, 1)

    def _split_range(self, sn: int, start_ch: int, start_vs: int, end_ch: int, end_vs: int):
        """
        将连续范围按章切割成多个 (ch, vs_start, vs_end) 段
        """
        segments = []
        max_chapter = self.sn_info[sn]['chapters']
        
        if start_ch < 1 or start_ch > max_chapter:
            return segments
        if end_ch < 1 or end_ch > max_chapter:
            return segments
        
        for ch in range(start_ch, end_ch + 1):
            max_verse = self._get_max_verse(sn, ch)
            
            if ch == start_ch and ch == end_ch:
                vs_start = start_vs
                vs_end = end_vs
            elif ch == start_ch:
                vs_start = start_vs
                vs_end = max_verse
            elif ch == end_ch:
                vs_start = 1
                vs_end = end_vs
            else:
                vs_start = 1
                vs_end = max_verse
            
            if vs_start < 1:
                vs_start = 1
            if vs_end > max_verse:
                vs_end = max_verse
            
            if vs_start <= vs_end:
                segments.append((ch, vs_start, vs_end))
        
        return segments
    
    def _query_single(self, result: QueryResult, book_short: str, chapter: int, start_vs: int, end_vs: int):
        """
        查询单个范围（内部方法）
        
        Args:
            result: 查询结果对象（会被修改）
            book_short: 书卷简称
            chapter: 章号
            start_vs: 起始节号
            end_vs: 结束节号
        """
        sn = self.short_to_sn.get(book_short)
        if not sn:
            result.errors.append(f"未知书卷: {book_short}")
            return
        
        self.cursor.execute("""
            SELECT VerseSN, Lection
            FROM Bible
            WHERE VolumeSN = ? AND ChapterSN = ? AND VerseSN BETWEEN ? AND ?
            ORDER BY VerseSN
        """, (sn, chapter, start_vs, end_vs))
        
        rows = self.cursor.fetchall()
        if not rows:
            result.warnings.append(f"未找到: {book_short}{chapter}:{start_vs}-{end_vs}")
            return
        
        book_full = self.short_to_full[book_short]
        testament = self.sn_info[sn]['testament']
        
        for verse_sn, text in rows:
            result.data.append(Verse(
                book_name=book_full,
                book_short=book_short,
                chapter=chapter,
                verse=verse_sn,
                text=text,
                testament=testament
            ))
    
    def get_books(self) -> List[Dict[str, Any]]:
        """
        获取所有书卷列表
        
        Returns:
            List[Dict]: 书卷信息列表，每项包含 sn, short, full, chapters, testament
        
        Example:
            >>> books = engine.get_books()
            >>> for b in books[:3]:
            ...     print(f"{b['short']} -> {b['full']} ({b['chapters']}章)")
            创 -> 创世记 (50章)
            出 -> 出埃及记 (40章)
            利 -> 利未记 (27章)
        """
        books = []
        for sn, info in self.sn_info.items():
            books.append({
                'sn': sn,
                'short': info['short'],
                'full': info['full'],
                'chapters': info['chapters'],
                'testament': info['testament']
            })
        return books
    
    def search(self, keyword: str, limit: int = 50) -> List[Verse]:
        """
        关键词搜索经文
        
        Args:
            keyword: 搜索关键词
            limit: 返回结果数量限制，默认 50
        
        Returns:
            List[Verse]: 匹配的经文列表
        
        Example:
            >>> verses = engine.search("爱", limit=5)
            >>> for v in verses:
            ...     print(f"{v.book_name}{v.chapter}:{v.verse}")
            约翰福音3:16
            哥林多前书13:4
            ...
        """
        self.cursor.execute("""
            SELECT b.VolumeSN, b.ChapterSN, b.VerseSN, b.Lection,
                   bi.FullName, bi.ShortName, bi.NewOrOld
            FROM Bible b
            JOIN BibleID bi ON b.VolumeSN = bi.SN
            WHERE b.Lection LIKE ?
            LIMIT ?
        """, (f'%{keyword}%', limit))
        
        verses = []
        for row in self.cursor.fetchall():
            verses.append(Verse(
                book_name=row[4],
                book_short=row[5],
                chapter=row[1],
                verse=row[2],
                text=row[3],
                testament='旧约' if row[6] == 0 else '新约'
            ))
        return verses
    
    def format_result(self, result: QueryResult) -> str:
        """
        格式化查询结果为可读文本
        
        自动合并连续的节号，按书卷和章节分组显示。
        
        Args:
            result: 查询结果对象
        
        Returns:
            str: 格式化后的文本
        
        Example:
            >>> result = engine.query("诗122:1-2,4-5,8")
            >>> print(engine.format_result(result))
            诗篇122:1-2,4-5,8
                1 人对我说：我们往耶和华的殿去...
                2 耶路撒冷啊，我们的脚站在你的门内。
                4 众支派，就是耶和华的支派...
                5 因为在那里设立审判的宝座...
                8 因我弟兄和同伴的缘故...
        """
        if not result.success:
            return f"❌ 查询失败:\n" + "\n".join(result.errors)
        
        if not result.data:
            return "⚠️ 未找到匹配的经文"
        
        output_lines = []
        
        # 按书卷分组
        book_groups = {}
        for verse in result.data:
            if verse.book_name not in book_groups:
                book_groups[verse.book_name] = []
            book_groups[verse.book_name].append(verse)
        
        # 处理每个书卷
        for book_name, verses in book_groups.items():
            # 按章节分组
            chapter_groups = {}
            for verse in verses:
                if verse.chapter not in chapter_groups:
                    chapter_groups[verse.chapter] = []
                chapter_groups[verse.chapter].append(verse)
            
            # 处理每个章节
            chapter_lines = []
            for chapter in sorted(chapter_groups.keys()):
                chapter_verses = sorted(chapter_groups[chapter], key=lambda v: v.verse)
                
                # 收集所有节号
                verse_numbers = [v.verse for v in chapter_verses]
                
                # 合并连续的节号
                ranges = []
                start = verse_numbers[0]
                end = verse_numbers[0]
                
                for i in range(1, len(verse_numbers)):
                    if verse_numbers[i] == end + 1:
                        end = verse_numbers[i]
                    else:
                        if start == end:
                            ranges.append(str(start))
                        else:
                            ranges.append(f"{start}-{end}")
                        start = verse_numbers[i]
                        end = verse_numbers[i]
                
                # 处理最后一组
                if start == end:
                    ranges.append(str(start))
                else:
                    ranges.append(f"{start}-{end}")
                
                # 生成章节标题
                range_str = ",".join(ranges)
                chapter_lines.append(f"{book_name}{chapter}:{range_str}")
                
                # 添加经文内容
                for verse in chapter_verses:
                    chapter_lines.append(f"{verse.verse} {verse.text}")
            
            output_lines.extend(chapter_lines)
            output_lines.append("")  # 书卷之间空行
        
        return "\n".join(output_lines).strip()
    
    def close(self):
        """
        关闭数据库连接
        
        使用完成后应调用此方法释放资源。
        
        Example:
            >>> engine = BibleEngine()
            >>> try:
            ...     result = engine.query("约3:16")
            ...     print(result)
            ... finally:
            ...     engine.close()
        """
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()