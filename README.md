# Adaptive Voxel Web：自适应体素、表面贴图与统一体素导出

这是一个本地运行的 GLB 三维模型处理演示。它把处理过程分成三个彼此独立的阶段：后端分析几何并生成自适应体素；浏览器从原模型采样颜色并渲染体素表面；用户可选地把自适应体素细分为统一尺寸的体素，并导出 GLB。

> **使用与引用限制**
>
> 如在课程、演示、软件或其他材料中使用本项目的代码、算法实现、流程、参数设计、图表或衍生成果，必须清楚注明来源，至少写明仓库链接、所用版本或 commit，并标出实际复用的模块。也必须分别遵循第三方库、模型和数据各自的许可证及署名要求。
>
> **本项目及其技术实现、实验结果和衍生成果不得用于论文发表、投稿或作为论文的方法、数据、结果及图表。** 不得通过改写或包装规避此限制。
>
> 本仓库没有声明开放源代码许可证。GitHub 上可见不等于获得复制、再发布、商用或论文使用授权；如需超出上述范围使用，须先取得作者书面许可。

## 功能概览

### 1. 几何分析与自适应体素化

后端接收 GLB，将场景变换应用到网格并归一化坐标，然后构造深度上限为 5 的占据真值网格，计算曲率、法线变化、局部几何误差和厚度等几何信号。规划器从八叉树根节点向下细分：主体区域倾向使用较大体素，几何特征明显的区域允许使用较小体素。

规划结果经过覆盖、连通性、悬浮体素和空隙等检查。目标成品尺寸与最小打印体素尺寸会共同限制允许的细分深度；若细节要求与打印尺寸下限冲突，系统可能放大目标成品尺寸。该流程是几何演示，不保证对开放、自交或严重破损网格进行制造级修复。

### 2. 与几何解耦的表面颜色采样

颜色采样在浏览器前端执行，不参与后端体素规划。程序针对每个体素的六个外露面分别采样：先沿面法线使用 BVH 对原模型进行射线查询，命中三角面后通过重心坐标插值 UV，再读取原贴图颜色。未命中时使用受距离、表面法线与方向约束的邻近表面回退，并在单个面内补齐映射空隙，以减少贴图漏采和相邻部件间的颜色串扰。

采样结果存入颜色图集，并由实例化网格显示。Color Detail 提供 2×2 至 64×64 网格（默认 32×32）；颜色简化和贴图开关只更新显示层。它们不会重新调用 Geometry Voxelization，也不会改变自适应体素的数量、位置或尺寸。

### 3. 自适应体素的统一细分与 GLB 导出

Uniformize 使用现有自适应体素的最小边长作为统一网格尺寸，将每个父体素按整数倍划分为子体素。该步骤不重新读取模型、不重新体素化，也不重新采样颜色；子体素沿用父体素的颜色区域和来源 ID。

细分时会检查网格对齐、整数倍关系、重叠、空隙、总体积和包围盒。输入不满足规则时会报错，不自动移动或修补几何。检查通过后可查看细分前后结果，并将统一体素网格导出为 `uniform_voxel_model.glb`。

## 处理流程

```text
GLB 输入
  → 后端网格清理与归一化
  → 占据真值、几何特征分析与自适应八叉树
  → 浏览器逐面采样原模型颜色并显示体素
  → （可选）按整数网格细分为统一体素
  → （可选）导出 uniform_voxel_model.glb
```

颜色显示阶段与几何体素化阶段相互独立；统一细分仅处理已生成的体素及其颜色数据。

## 快速启动（Windows）

1. 下载或克隆本仓库，并保持 `backend`、`frontend/dist` 和 `samples` 的目录关系。
2. 安装 Python 3.11 或 3.12。
3. 双击 `启动网站.bat`，或在仓库根目录运行：

   ```powershell
   python start_local.py
   ```

4. 首次启动时，如果当前 Python 环境缺少后端依赖，启动器会在仓库内创建 `.venv` 并安装 `backend/requirements.txt` 中的依赖。首次安装需要网络。
5. 启动器默认从 `127.0.0.1:8003` 开始寻找可用端口，并自动打开浏览器；实际地址以终端输出为准。按 `Ctrl+C` 停止服务。

发布包已包含 `frontend/dist`，日常运行不需要安装 Node.js。服务只绑定本机回环地址；不要直接双击 `index.html`，页面需要本地 HTTP 服务和 Python 后端。

## 开发运行

后端服务：

```powershell
python -m pip install -r backend/requirements.txt
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8003
```

前端开发服务（另开终端）：

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Vite 默认将 `/api` 和 `/samples` 转发到 `127.0.0.1:8003`。前端变更后运行 `pnpm build`，更新 `frontend/dist`。

## 界面与参数

- 上传 `.glb` 后可切换 Original Color、Curvature、Thickness、Octree Depth 和 Voxel Color 视图；也可加载 `samples` 中的内置模型。
- 鼠标左键旋转、滚轮缩放、右键平移；Grid 控制网格显示，Frame 控制模型居中。
- Geometry Detail 控制细节预算；Curvature Priority、Thin Feature Priority 等参数影响几何特征权重。算法默认权重与边界见 `backend/config.py` 和 `frontend/src/controls.js`。
- Minimum Voxel Size 按目标打印尺寸解释，不把 GLB 原始坐标单位当作毫米。后端默认目标模型最长边为 320 mm、打印体素下限为 10 mm，最大八叉树深度为 5；实际值会显示在界面统计中。
- Color Detail 默认 32×32。颜色面板只影响外观显示；改变几何参数才会重新请求 `/api/voxelize`。
- 完成颜色采样后可运行 Uniformize，查看 Before/After，并导出 GLB。

上传限制为 40 MB，输入必须是有效 GLB。处理依赖网格质量和本机环境；模型过大、缓存过期或几何无效时，页面会显示错误。

## 技术结构

| 部分 | 主要职责 | 代码位置 |
|---|---|---|
| 启动器与本地服务 | 创建可用 Python 环境、选择本机端口、启动 API 并打开页面 | `start_local.py`、`启动网站.bat`、`backend/main.py` |
| 网格与几何分析 | GLB 读取、坐标处理、占据真值、曲率/法线/厚度/局部误差分析 | `backend/meshio/`、`backend/geometry/` |
| 自适应规划与检查 | 八叉树规划、拓扑与空隙保护、结果验证和序列化 | `backend/octree/` |
| 浏览器查看与贴图 | Three.js 模型显示、BVH 查询、逐面 UV/颜色采样、颜色图集 | `frontend/src/viewer.js`、`colorSampler.js`、`voxelRenderer.js` |
| 统一细分与导出 | 整数网格划分、约束检查、前后预览与 GLB 导出 | `frontend/src/uniformizer.js`、`viewer.js` |
| 发布前端 | 本地服务直接提供的构建产物 | `frontend/dist/` |

## API 概要

| 方法与路径 | 用途 |
|---|---|
| `GET /api/health` | 服务状态、最大深度与缓存容量 |
| `POST /api/upload` | 上传 GLB，返回模型 ID 和处理状态；请求体为 multipart `file` |
| `GET /api/models/{model_id}` | 查询处理阶段、警告和分析耗时 |
| `GET /api/models/{model_id}/analysis` | 获取曲率与厚度等分析数据 |
| `POST /api/voxelize` | 根据模型 ID 与几何参数生成自适应体素及统计信息 |

模型分析使用单个工作线程；内存 LRU 缓存最多保留三个模型，服务重启后清空。模型仍在处理时，体素化请求返回 409；模型不在缓存中时返回 404；几何处理失败时返回 422。

## 依赖与来源记录

前端依赖及锁定版本范围见 `frontend/package.json` 和 `frontend/pnpm-lock.yaml`；后端依赖范围见 `backend/requirements.txt`。主要技术包括 Three.js、`three-mesh-bvh`、FastAPI、Trimesh、Open3D、libigl、NumPy 和 SciPy。使用或再分发依赖时，应核对各自官方文档、作者信息与许可证，并遵守其署名条款：

- [Three.js](https://threejs.org/)
- [three-mesh-bvh](https://github.com/gkjohnson/three-mesh-bvh)
- [FastAPI](https://fastapi.tiangolo.com/)
- [Trimesh](https://trimesh.org/)
- [Open3D](https://www.open3d.org/)
- [libigl](https://libigl.github.io/)
- [NumPy](https://numpy.org/)、[SciPy](https://scipy.org/)

### 建议的项目来源写法

在允许使用的材料中，按实际使用版本填写并引用：

> XinAn-Annie, *Adaptive Voxel Web: Adaptive Voxelization, Surface Texture Sampling and Uniform Voxel Export*, GitHub repository, `https://github.com/XinAn-Annie/Voxel`, commit `<填写实际使用的 commit SHA>`, accessed `<访问日期>`.

引用项目仓库不能代替第三方依赖、外部算法、数据或模型本身的来源说明。请在使用材料中逐项列出实际复用内容及其来源。**论文投稿与发表仍受本项目的禁止使用限制约束。**

## 目录

```text
backend/                 Python API、网格分析、自适应八叉树
frontend/src/            WebGL 查看器、贴图采样、统一细分与导出
frontend/dist/           发布构建
samples/                 内置 GLB 示例
scripts/                 模型生成与检查脚本
tests/                   项目验证材料
实验1/                   项目随附的实验输出
start_local.py           本机启动器
启动网站.bat              Windows 启动入口
```