# first_reading.py - 使用示例
from bible_engine import BibleEngine

def main():
    # 初始化引擎
    from bible_engine import BibleEngine
    engine = BibleEngine()
    print(engine.query_formatted("诗122:1—2；4-5，8，123：2；希伯来书 10:25，27；约3：16"))
    
    # 关闭连接
    engine.close()

if __name__ == "__main__":
    main()