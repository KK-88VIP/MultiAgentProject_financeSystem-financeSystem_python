# financeSystem_python

Python 后端项目骨架，面向《财务数据分析看板与智能问数系统》MVP 实现。

## 启动方式

```powershell
# 激活虚拟环境
& "E:\MultiAgentProject_financeSystem\python_env\openclaw_env\Scripts\Activate.ps1"

# 安装依赖
pip install -r requirements.txt

# 启动项目
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## 当前状态

- 已完成项目目录初始化
- 已完成基础 FastAPI 入口与占位接口
- 已完成每个 `.py` 文件基础头信息初始化
- 待实现真实业务逻辑、数据库接入、问数编排与安全校验
