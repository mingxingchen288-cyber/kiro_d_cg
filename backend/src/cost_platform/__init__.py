"""配置驱动的成本业务平台（后端）。

模块划分和依赖规则见 docs/架构与组装.md 第 2、3 节，由 import-linter 检查（backend/.importlinter）：
业务模块只依赖 contracts，彼此不导入；只有 assembly 可以导入业务模块。
"""

__version__ = "0.1.0"
