# Adaptive Voxelizer V5 · 特征显著性自适应体素化

V5 的目标不是均匀逼近表面，而是用大体素概括主体，用较小体素保留曲率、轮廓、凹凸、局部拟合误差和材质分件显著性较高的辨识特征。输出仍受打印最小边长、空隙防桥接、闭合覆盖和单连通约束。

## 最简单的启动方式（Windows）

1. 完整解压 ZIP。请保留 `backend`、`frontend/dist`、`samples` 的相对位置。
2. 安装 Python 3.11 或 3.12，并加入 PATH；本次验证使用 Python 3.12。
3. 双击 **启动网站.bat**。也可以运行 `python start_local.py`。
4. 如果当前 Python 缺少依赖，启动器会创建项目内 `.venv` 并安装依赖；首次安装需要网络，Open3D 较大，请等待终端完成。
5. 浏览器自动打开 `http://127.0.0.1:8000`。端口占用时自动尝试后续端口，以终端显示地址为准。

发布包已附生产构建，日常使用不需要安装 Node 或重新构建前端。依赖安装完成后，模型分析全部在本机运行，页面资源和样例不依赖外部网站。关闭服务窗口或按 Ctrl+C 可停止。

**不要直接双击 index.html**：它需要 HTTP 服务和 Python 几何后端。服务器仅监听本机地址，不会发布到互联网。

## 开发模式：分别安装前后端

后端（在项目根目录打开终端）：

```powershell
python -m pip install -r backend/requirements.txt
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

前端需要 Node.js 20.19+ 或 22.12+，以及 pnpm。在另一终端：

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

打开 Vite 显示的地址（通常是 `http://127.0.0.1:5173`）。Vite 将 `/api` 和 `/samples` 转发到后端。修改后运行 `pnpm build` 更新 `frontend/dist`；再从 Python 服务访问即可使用新构建。

## 使用方法

- 点击 Upload GLB 选择 `.glb`。限制 40 MB、150,000 三角面。原模型立即显示，后台第一次分析需要数秒；状态栏显示当前阶段。
- 或在右侧选择 Cube、Sphere、Cube + Thin Rod、Cone、Animal / Character，点击 Load。五个原创程序化样例均包含在 `samples` 中，与上传共用处理流程。
- 左键拖动旋转、滚轮缩放、右键拖动平移；右上角瞄准按钮重新居中；Grid 开关控制网格。
- Original Color 显示 GLB 原始 texture / vertex color / material color。Curvature / Thickness 显示分析网格上对应的标量场，并附图例。厚度无法估计时显示灰色。
- Octree Depth 用不同颜色区分层级；Voxel Color 按 texture/UV → vertex color → material color → 默认色的优先级显示体素表面。Color Detail 只细分表面色块，不产生新 voxel。

Texture / Color 面板完全在浏览器显示层工作。Color Detail 提供 2×2、4×4、8×8、16×16、32×32、64×64（默认 32×32），Color Simplification 合并相近颜色，Enable Texture 控制彩色/中性显示，Reset Color 恢复默认值。每个 voxel 的每个外露面会建立独立采样网格；采样点先沿该面法线向原模型执行 BVH raycast，命中 triangle 后以 barycentric coordinates 插值原 UV 并读取贴图。只有 raycast 未命中时才使用有最大距离、表面法线和方向约束的 nearest-surface fallback，避免穿透模型、跨部件或跨到模型另一侧。修改这些参数不会请求 `/api/voxelize`，不会改变 octree、voxel 数量或体素尺寸，也不会重置相机。

## 参数含义

| 参数 | 行为 |
|---|---|
| Minimum Voxel Size | 按最终成品尺寸换算，默认成品最长边 `180 mm`、体素边长硬下限 `10.1 mm`（可通过 voxelize API 的 `target_model_size_mm` 与 `min_printed_voxel_mm` 调整）。GLB 原始坐标只用于导入，不代表打印米数。 |
| Geometry Detail | 0–100%。直接控制全局细节预算；默认 40%。低、中、高显著性区域采用不同深度上限，因此向右调整不会退化为均匀体素化。 |
| Curvature Priority | 曲率与邻域曲率变化的权重，默认 0.40。提高弯曲、尖角和曲率快速变化区域的重要程度。 |
| Thin Feature Priority | 厚度辅助权重，默认 0.10。薄度不能单独触发细分，避免平滑四肢产生过多小体素。 |

法线权重固定为 0.25，局部几何误差权重固定为 0.25。四个参数可用 Reset 一次恢复默认值。滑块停止约 200 ms 后请求更新，旧请求会被取消，过期结果不会覆盖新模型。

底部统计显示体素数量、实际最小尺寸、层级范围和缓存裁剪耗时；下面另列浏览器请求与显示耗时。首次分析耗时与滑块更新耗时不同，不能混淆。`<300 ms` 是缓存更新目标；本次五个样例的实际结果记录在 `tests/backend-results.json`，不代表所有硬件和极端参数都保证相同速度。

## V5 算法流程

1. GLB 场景节点先应用变换并按比例归一化；非闭合输入生成密闭代理，只用于深度 5 的实心 occupancy truth。
2. 在 32³ truth 网格上计算局部法线突变、signed-distance 凹凸、局部拟合残差，以及小尺度/高材质对比分件与主体的交界；稳定连续曲率和普通主体分件接缝不再作为强细分理由。
3. 各项形成 `geometric saliency`，并只向一个邻域扩散。父块使用显著性第 90 百分位而不是最大值，避免单个噪声点带动整片光滑曲面细分。
4. `feature_planner.py` 从八叉树根部自顶向下规划。低显著性主体优先停在深度 2–3，结构交界和面部特征停在 3–4，仅最高显著性区域允许到 5；滑块改变各档预算但始终保留相对层级。
5. 低 occupancy 本身不再等于高复杂度，仅低于 8% 时防止一个表面碎片膨胀成巨块；包含多个局部连通分量的父块必须拆分。额外记录原网格组件邻接关系，并同时保护三维组件间通道和三个主轴投影中的凹形轮廓空隙；任何父块都不得覆盖耳间、腿间等真实空隙。
6. 后端验证输出覆盖、错误桥接、悬浮分量、深度分布和 feature/structure 数量。打印边长由目标成品尺寸换算，最大深度固定不超过 5，默认最小边长为 1 cm。

算法参数集中在 `backend/config.py`；UI 参数范围、映射和防抖在 `frontend/src/controls.js`。这是一版几何 Demo：法线射线厚度是局部估计，复杂自交/开放表面不能保证准确体积，警告会显示在页面。它不承诺制造级几何修复。

## API

| 接口 | 用途 |
|---|---|
| `GET /api/health` | 服务状态 |
| `POST /api/upload` | multipart `file`，返回 HTTP 202、model_id 和 processing/ready 状态 |
| `GET /api/models/{id}` | 轮询分析阶段、警告、变换矩阵、首次分析耗时和运行次数 |
| `GET /api/models/{id}/analysis` | 一次获取分析网格与曲率/厚度标量 |
| `POST /api/voxelize` | 传入 model_id 和参数，仅重新裁剪缓存，返回 voxels 与 stats |

缓存为进程内 LRU，最多三个模型；重启后清空。相同 GLB 复用缓存。分析由单独工作线程排队执行；未完成时 voxelize 返回 409；缓存失效返回 404；几何错误返回 422。页面显示错误并允许重新上传。

## 项目结构

```text
backend/
  api/routes.py          上传、后台分析、状态与体素 API
  meshio/mesh_loader.py  GLB 场景处理与归一化（避免与 Python 内置 io 重名）
  geometry/             curvature / thickness / normals / importance
  octree/               node / builder / pruning
  cache/store.py        模型与候选树缓存
  config.py             算法配置
  main.py               API 与发布版静态文件服务
frontend/
  src/                  main / viewer / uploader / api / controls / voxelRenderer / style
  dist/                 已构建、可直接由 Python 服务的完整前端
samples/                五个 GLB 测试模型
scripts/                测试模型生成及验证脚本
tests/                  实际测试结果与浏览器截图
start_local.py           启动器
启动网站.bat             Windows 入口
```

## 重跑验证

```powershell
python -m pip install -r backend/requirements.txt -r scripts/requirements-test.txt
python scripts/check_backend.py
python scripts/check_real_models.py "D:\path\to\fox_simplified.glb"
```

要重新生成内置原创测试模型，可运行 `python scripts/generate_models.py`。测试脚本与模型数据不参与日常服务；无需安装测试依赖也能使用发布包内的已有 GLB。
