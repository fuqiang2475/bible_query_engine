# Bible Query Engine

一个支持复杂引用格式的 SQLite 圣经查询引擎。

## 数据来源

本工具使用的数据库来自 [ElijahLabs/bible](https://github.com/ElijahLabs/bible)，在此致谢！
功能
支持中英文标点：； , ， 、 - —
支持多节、多章、跨书卷引用
自动合并连续节号
返回固定引用格式的文本

### 快速开始
python
from bible_engine import BibleEngine
engine = BibleEngine('bible.db')
print(engine.query_formatted("诗122:1-2,4-5；希伯来书10:25,27"))

### 引用格式示例
输入	说明
诗122:1	单节
诗122:1-5	连续范围
诗122:1,3,5	多节
诗122:1-2,4-5,8	混合
诗122:1-5；123:2	多章
希伯来书10:25,27	中文全称
### API
方法	说明
query(ref)	返回结构化 QueryResult 对象
query_formatted(ref)	返回特定格式的文本
search(keyword)	关键词搜索
get_books()	获取全部书卷列表
### 依赖
Python 3.8.10+
sqlite3（内置）
