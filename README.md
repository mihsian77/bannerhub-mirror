# bannerhub-mirror

**GameHub 官方组件文件的完整备份。**

客户端能下载的每一个组件，都在这个仓库里留了一份原样副本：同一个文件名、同一份字节，附上 MD5 与 SHA-256。上游某个 release 被删、被改 tag、资产被清空的时候，这里还能取到。

这个仓库不是「我们项目用到的组件列表」，也不是某个作者的个人构建合集。判定标准只有一条：**在不在 GameHub 的官方组件目录里**。

## 数据源

唯一来源：

```
https://the412banner.github.io/bannerhub-api/simulator/v2/getAllComponentList
```

这是客户端启动时拉的组件清单，返回 640 条，每条带 `display_name` / `name` / `version` / `file_name` / `file_md5` / `file_size` / `download_url`。640 条去重后是 **639 个文件、4.07 GB**，全部托管在 `The412Banner/bannerhub-api` 的 `Components` release 下。

`upstream.json` 里只有这一个源。脚本遇到非 `catalog` 类型的源会直接跳过并打警告——多加一个源，这个仓库就不再是「官方备份」了。

> 目录里 307 条的 `display_name` 是空的，`file_name` 又常常是 `md5.tzst`，看着像「没有名字」。真实名称在 `name` 字段里（如 `Box64-0.4.4-Bionic`、`dxvk-1.7.3`），[`manifests/CATALOG.md`](manifests/CATALOG.md) 已按分类整理成人能读的表。

## 分类

按官方目录的 `type` 字段切分，一一对应，不加不减：

| Release | type | 条数 | 体积 | 内容 |
|---|---:|---:|---:|---|
| [`drivers`](../../releases/tag/drivers) | 2 | 323 | 1.14 GB | Adreno / Turnip / Qualcomm 驱动包 |
| [`settings`](../../releases/tag/settings) | 5 | 69 | 1.85 GB | 游戏配置包 + Wine / Proton 容器 |
| [`runtime-yml`](../../releases/tag/runtime-yml) | 6 | 121 | <0.01 GB | 运行库定义，每项一个 yml |
| [`dxvk`](../../releases/tag/dxvk) | 3 | 68 | 0.66 GB | DXVK |
| [`fex`](../../releases/tag/fex) | 1 | 31 | 0.17 GB | FEXCore |
| [`box64`](../../releases/tag/box64) | 1 | 13 | 0.06 GB | Box64 |
| [`vkd3d`](../../releases/tag/vkd3d) | 4 | 11 | 0.04 GB | VKD3D-Proton |
| [`steam`](../../releases/tag/steam) | 7 | 3 | 0.15 GB | Steam 客户端打包 |
| **合计** | | **639** | **4.07 GB** | |

`type=1` 是转换层，里面 Box64 和 FEXCore 混在一起，按 `name` 前缀拆成两个 Release。其余 type 与 Release 严格一对一。

资产名保持官方原名，不重命名——这样 `download_url` 的末段可以直接对上资产名，URL 能原样还原。

直链形如：

```
https://github.com/mihsian77/bannerhub-mirror/releases/download/dxvk/dxvk-1.7.3.tzst
```

`tag` 固定，文件只增不删，URL 可以硬编码。

## 目录

```
upstream.json              唯一数据源 + type → Release 的映射
manifests/catalog.json     全部 639 条的机读清单（含 md5 / 大小 / 原 URL）
manifests/CATALOG.md       同一份清单的人读版，按分类排列
state/<bucket>.json        已镜像文件 → 大小 / sha256 / md5 / 资产名
tools/mirror.py            同步脚本，标准库实现，无依赖
.github/workflows/         每天 03:00 (Asia/Shanghai) 自动跑
```

## 自动跟随

每天定时按分类并行跑：拉官方目录 → 比对 `state/<bucket>.json` → 只下载缺的 → 校验 MD5 → 上传到对应 Release → 回写状态。MD5 与目录声明不符的直接丢弃、不记入状态，下一轮重试。

8 个分类各自一个 Release，最大的 `drivers` 是 323 个资产，远低于 GitHub 单 Release 1000 个资产的上限，不需要分片。

手动触发：

```bash
GH_TOKEN=xxx MIRROR_REPO=owner/bannerhub-mirror \
  python3 tools/mirror.py --sync --bucket dxvk
python3 tools/mirror.py --check        # 只看差多少，不下载
python3 tools/mirror.py --manifest     # 重写 manifests/ 两份清单
```

## 边界

- 只转存 GameHub 官方目录里列出的文件，不做任何第三方源的聚合，也没有本仓库自己的二进制。
- 不含客户端的私有接口参数、资源或修改；不涉及对客户端的任何改动。
- 不托管游戏本体、Steam / Epic 内容、付费资源。`steam` 分类是官方目录本来就下发的客户端打包，照原样留档。
- 每个文件的权利归其上游作者。本仓库只做保留备份，收到作者异议即下架对应资产。
- 本仓库自身代码为 MIT。

> 已知上游缺文件：`Resident Evil 3`、`Torchlight II`、`WRC 9` 三条例在目录里、`bannerhub-api` 的 release 里却没有，两种文件名写法都是 404。补不了，等上游自己修。
