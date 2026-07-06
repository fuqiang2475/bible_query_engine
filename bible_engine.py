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
        
        支持同一书卷的多个章节和范围。
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
            result.errors.append("引用为空")
            return result
        
        ref = ref.strip()
        
        # 提取书名
        book_short = None
        remaining = ref
        
        # 尝试全称
        for short, full in self.short_to_full.items():
            if ref.startswith(full):
                book_short = short
                remaining = ref[len(full):].strip()
                break
        
        # 尝试简称
        if not book_short:
            book_match = re.match(r'^([\u4e00-\u9fa5]+)', ref)
            if book_match:
                possible_book = book_match.group(1)
                if possible_book in self.short_to_sn:
                    book_short = possible_book
                    remaining = ref[len(possible_book):].strip()
        
        if not book_short:
            result.success = False
            result.errors.append(f"无法识别书名: {ref}")
            return result
        
        sn = self.short_to_sn[book_short]
        
        # 查找后续书卷的位置（用于分割）
        next_book_pos = len(remaining)
        for short in self.all_shorts:
            pos = remaining.find(short)
            if pos != -1 and pos < next_book_pos:
                next_book_pos = pos
        for short, full in self.short_to_full.items():
            pos = remaining.find(full)
            if pos != -1 and pos < next_book_pos:
                next_book_pos = pos
        
        # 分割：当前书卷的部分 + 后续书卷的部分
        current_part = remaining[:next_book_pos].strip()
        rest_part = remaining[next_book_pos:].strip() if next_book_pos < len(remaining) else ""
        
        # 先处理当前书卷
        if current_part:
            pattern = r'(\d+)\s*[:：]\s*([^:：]*?)(?=\s*\d+\s*[:：]|$)'
            matches = re.findall(pattern, current_part)
            
            for chapter_str, ranges_str in matches:
                chapter = int(chapter_str.strip())
                
                if chapter <= 0 or chapter > self.sn_info[sn]['chapters']:
                    result.errors.append(f"章号 {chapter} 超出范围")
                    continue
                
                max_verse = self._get_max_verse(sn, chapter)
                range_parts = re.split(r'[；;，,、]', ranges_str.strip())
                
                for range_str in range_parts:
                    range_str = range_str.strip()
                    if not range_str:
                        continue
                    
                    if re.search(r'[-–—]', range_str):
                        nums = re.split(r'[-–—]', range_str)
                        if len(nums) == 2:
                            try:
                                start_vs = int(nums[0].strip())
                                end_vs = int(nums[1].strip())
                                if 0 < start_vs <= max_verse and 0 < end_vs <= max_verse and start_vs <= end_vs:
                                    self._query_single(result, book_short, chapter, start_vs, end_vs)
                                else:
                                    result.errors.append(f"无效节范围: {start_vs}-{end_vs}")
                            except ValueError:
                                result.errors.append(f"无效范围: {range_str}")
                    else:
                        try:
                            verse = int(range_str)
                            if 0 < verse <= max_verse:
                                self._query_single(result, book_short, chapter, verse, verse)
                            else:
                                result.errors.append(f"节 {verse} 超出范围")
                        except ValueError:
                            result.errors.append(f"无效节号: {range_str}")
        
        # 然后处理后续书卷（保证顺序）
        if rest_part:
            rest_result = self._query_single_ref(rest_part)
            result.data.extend(rest_result.data)
            if not rest_result.success:
                result.success = False
                result.errors.extend(rest_result.errors)
            result.warnings.extend(rest_result.warnings)
        
        if result.errors and not result.data:
            result.success = False
        
        return result
    
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
                    chapter_lines.append(f"    {verse.verse} {verse.text}")
            
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