# ecommerce-after-sales-system

当前项目已经统一成：

- 前端：`frontend/uniapp`
- 主后端：Spring Boot
- AI 售后 Agent：仓库内 `python_agent/`

前端不要直接连 Python，统一只连 Spring Boot 的 `/api/*`。

## 本地联调入口

- Spring Boot API: `http://127.0.0.1:8081/api`
- Python Agent API: `http://127.0.0.1:8000/api`
- H5 调试端: `http://localhost:5173/#/`

## Agent 联调说明

Spring Boot 已经代理以下接口到 Python Agent：

- `GET /api/agent/health`
- `POST /api/agent/review-images`
- `POST /api/agent/chat`

默认情况下，Spring Boot 启动时会自动尝试拉起仓库内的 `python_agent/web_demo.py`。
如果你不想自动拉起，可以配置：

- `AGENT_AUTO_START=false`
- `AGENT_PYTHON_COMMAND=python`
- `AGENT_SCRIPT_PATH=python_agent/web_demo.py`

Python 代码已经放进当前仓库：

- [python_agent/web_demo.py](D:\Users\林先锐\Desktop\大三实训\小程序端\ecommerce-after-sales-system-main\ecommerce-after-sales-system-main\python_agent\web_demo.py)
- [python_agent/after_sales_agent](D:\Users\林先锐\Desktop\大三实训\小程序端\ecommerce-after-sales-system-main\ecommerce-after-sales-system-main\python_agent\after_sales_agent)

说明：

- `python_agent/sample_images` 里的图片是售后凭证审核样例
- 这些图片不应该作为商城商品图上传到数据库
- 商品库里只保留正常售卖商品，例如手机、耳机、水壶
