import os
import sys

# 将项目根目录加入 sys.path，使测试可直接 import 顶层模块
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
