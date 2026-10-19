# AzurLaneTool

碧蓝航线数据管理工具：基于 Python + PyQt5 + SQLite 的本地桌面应用，围绕 **CRUD 数据管理与可视化** 组织功能。

> 当前代码属于历史迭代版本，处于持续补齐阶段。开发基线是 `develop`；`master` 暂为历史正式版分支，首个正式版发布前不作为日常开发/发布基线。

## 功能

- **数据看板**：收藏率、科技点、执勤天数、资源卡与日环比角标。
- **舰娘管理**：图鉴解锁、舰娘新增、觉醒、界限突破、誓约。
- **资源统计**：魔方 / 红尖尖常规录入、撤销、任务看板、结余链。
- **指级经验与心智计算**：指挥官快照、等级卡、经验效率。
- **本地优先**：数据存 SQLite，无服务端、无云同步。

## 技术栈

- Python >= 3.8（本机开发使用 3.12）
- PyQt5
- SQLite（标准库 `sqlite3`，无 ORM）
- unittest（测试）；PyInstaller（打包）

## 快速开始

### 1. 安装依赖

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

### 2. 运行

```powershell
python main.py
```

首次运行前请确认数据库存在：`data/AzurLaneStatisticalOfficeDB.db`。应用启动时会幂等补齐资源统计/魔方任务相关表；缺库时不会自动创建完整业务库。

### 3. 数据位置

| 路径 | 说明 |
|---|---|
| `data/AzurLaneStatisticalOfficeDB.db` | 主数据库（不入 Git） |
| `data/backup/` | 数据备份（不入 Git） |
| `data/user.json` | 本机用户数据，如执勤开始日期（不入 Git） |

## 测试

```powershell
# 全量
python -m unittest discover -s tests

# 单个模块
python -m unittest tests.test_time_refresh -v
```

- Qt 测试使用 `QT_QPA_PLATFORM=offscreen`。
- 测试使用临时数据库，不会读写 `data/` 下的真实库。
- 截至 2026-10-19 基线：26 个测试文件、390 项通过。

## 打包

```powershell
build.bat
# 或
pyinstaller build.spec --clean
```

- `build.spec` 是项目构建配置，已纳入 Git。
- 新增 `sql/` 文件或 `assets/` 资源时，必须同步 `build.spec` 的 `datas`。
- 输出：`dist/AzurLaneTool.exe`。

## 代码检查

```powershell
python -m flake8 .
python -m black --check .
```

- flake8 配置：`.flake8`（120 列，忽略 black 兼容项，测试允许长断言）。
- black 配置：`pyproject.toml`（120 列，保留单引号风格）。
- 构建脚本 `build.bat` 会执行 `python -m flake8 .`。

## 目录

```text
AzurLaneTool/
├─ main.py              应用入口
├─ views/               视图层（Qt Widgets）
├─ services/            业务逻辑层
├─ repositories/        数据访问层
├─ models/              数据模型（dataclass）
├─ sql/                 DDL / 查询 / 种子数据 / SQL 模板
├─ utils/               常量、连接、时间源、格式化、异常
├─ tests/               单元测试
├─ tools/               一次性迁移/对齐脚本
├─ docs/                需求、方案、迁移、复核、性能报告
├─ data/                本地数据库与用户数据（不入 Git）
├─ assets/              图标等静态资源
├─ build.bat            构建脚本
├─ build.spec           PyInstaller 配置
└─ requirements.txt     依赖声明
```

## 规范与文档

- 开发规范：[设计与开发规范文档.md](设计与开发规范文档.md)
- Issue 模板：`.github/ISSUE_TEMPLATE/`（缺陷 / 功能 / 数据 / 杂项 / 文档）
- 标签定义：`.github/labels.yml`
- 现有设计与报告：`docs/`
- 新文档命名：`docs/YYYYMMDD_主题.md`（旧文件保留原名，不追溯改名）
- 分支与提交流程、权限与批量授权：见规范第 8 节

## 说明

- `dsh-plugins/` 与 `.dsh/` 是本机 DSH 配置（Agent 插件、提示词、任务模板），已被忽略，不纳入 Git。
- 数据库、备份、`data/user.json`、构建产物、虚拟环境均不入 Git。
- 提交前请确认只暂存本轮文件，不要 `git add .`。
