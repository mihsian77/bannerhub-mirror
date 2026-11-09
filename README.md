# bannerhub-mirror

**GameHub 组件文件的完整备份。**

客户端能拿到的组件，在这里各留一份副本，附 MD5 与 SHA-256。上游 release 被删、被改 tag、资产被清空的时候，这里还能取到。

判定标准只有一条：**这个文件是不是 GameHub 自己能下到的**。不是「我们项目用到的」，也不是某个作者的个人构建合集。

## 收录范围

两个源，都属于 GameHub：

1. **组件目录** `getAllComponentList` —— 客户端启动时拉的索引，640 条，带 `name` / `version` / `file_md5` / `file_size` / `download_url`
2. **`Components` release 实际资产** —— 723 个文件。目录只索引了其中 640 条，剩下 145 个是 Wine/Proton 容器、imagefs 系统镜像、运行库安装包

两者的关系不是「源 A 补源 B」，而是**索引与实际文件对不齐**：

| 情况 | 数量 | 处理 |
|---|---:|---|
| 目录有、release 有 | 639 | 正常收录 |
| 目录有、release 没有 | 5 | 标为上游缺件（见文末） |
| release 有、目录没有 | 145 | 见下 |

那 145 个里：

- **36 个能看出是什么** —— `wine_proton11.0-arm64x-6.16.tar.zst`、`imagefs_142.zst`、`VC_redist.x64.exe`、`K-Lite_1982.exe` 这类，按内容归入 `wine` / `system` / `runtimes-bin`
- **109 个文件名是纯 md5** —— 逐个比对后发现 **78 个的 md5 与目录里某条完全相同**，是同一份文件被另存了一份，直接剔除；剩下 **31 个真正独有**，归入 `unindexed`

所以最终收录 **705 个文件 / 7.81 GB**。

> 关于「一堆 md5 名字的文件」：那是上游的上传习惯——同一份文件既用可读名存一份，又用内容 md5 存一份，目录只索引了可读名那份。本仓库不再保留重复件，且**资产名已全部规范化**，见下。

## 资产命名

release 里的资产名是规范化后的可读名，不再是 `00e8a606…tzst` 这种：

| 官方文件名 | 本仓库资产名 |
|---|---|
| `00e8a6065fe71084e7a9ff720d400f81.tzst` | `qcom-800.64.tzst` |
| `ce171769213ec56f46c0ab691d67ea95.tzst` | `turnip_v26.0.0_R1.tzst` |
| `dxvk-1.7.3.tzst` | `dxvk-1.7.3.tzst` |

原名、md5、官方 URL 全部记在 [`manifests/catalog.json`](manifests/catalog.json) 的 `official_file` / `md5` / `url` 字段，能反查回官方地址。人读版是 [`manifests/CATALOG.md`](manifests/CATALOG.md)，705 条按分类排好，含名称、版本、体积。

改名不影响校验：GameHub 认的是文件内容的 md5，不是文件名。

## 分类

| Release | 条数 | 体积 | 内容 |
|---|---:|---:|---|
| [`drivers`](../../releases/tag/drivers) | 326 | 1.14 GB | Adreno / Turnip / Qualcomm 驱动包 |
| [`settings`](../../releases/tag/settings) | 69 | 1.85 GB | 游戏配置包（每款游戏一个） |
| [`runtime-yml`](../../releases/tag/runtime-yml) | 122 | <0.01 GB | 运行库安装脚本 yml |
| [`dxvk`](../../releases/tag/dxvk) | 68 | 0.66 GB | DXVK |
| [`fex`](../../releases/tag/fex) | 31 | 0.17 GB | FEXCore |
| [`box64`](../../releases/tag/box64) | 13 | 0.06 GB | Box64 |
| [`vkd3d`](../../releases/tag/vkd3d) | 11 | 0.04 GB | VKD3D-Proton |
| [`steam`](../../releases/tag/steam) | 3 | 0.15 GB | Steam 客户端打包 |
| [`wine`](../../releases/tag/wine) | 5 | 1.18 GB | Wine / Proton 容器镜像 |
| [`system`](../../releases/tag/system) | 9 | 1.45 GB | imagefs 系统镜像与 base 包 |
| [`runtimes-bin`](../../releases/tag/runtimes-bin) | 14 | 0.31 GB | 运行库安装包本体（VC++ / PhysX / wine-mono / K-Lite） |
| [`unindexed`](../../releases/tag/unindexed) | 31 | 0.83 GB | 无索引独有文件，保留供比对 |
| **合计** | **705** | **7.81 GB** | |

`type` 与 Release 的对应：1→box64/fex，2→drivers，3→dxvk，4→vkd3d，5→settings，6→runtime-yml，7→steam。type=1 里 Box64 和 FEXCore 混在一起，按 `name` 前缀拆开。

直链形如：

```
https://github.com/mihsian77/bannerhub-mirror/releases/download/drivers/qcom-800.64.tzst
```

`tag` 固定，文件只增不删，URL 可以硬编码。

## 关于「运行库全是 yml」

这是 GameHub 自身的设计，不是备份缺东西。

`runtime-yml` 里的 121 个 yml 是**安装脚本**，例如：

```yaml
Name: amstream
Steps:
- action: cab_extract
  file_name: windows6.1-kb976932-x86_....exe
  url: http://download.windowsupdate.com/msdownload/update/software/svpk/2011/02/...
  file_checksum: 4bf28fc00d86c936c89e2d91ef46758b
```

客户端运行时按 `url` 现下，源站是微软、Harman、usebottles 等外站，不在 `Components` release 里。121 个 yml 共 334 条引用，指向 162 个不同的外部地址。

能收的都收了：`Components` release 里确实存在的那批安装包（VC_redist、PhysX、wine-mono、K-Lite、VulkanRT）在 `runtimes-bin` 里。剩下的外站文件不属于「GameHub 的分发物」，也不该由本仓库代存。

## 目录

```
upstream.json              两个源 + type→Release 映射 + 文件名修正表
manifests/catalog.json     705 条的机读清单（资产名 / 原名 / md5 / 体积 / 官方 URL）
manifests/CATALOG.md       同一份清单的人读版
state/<bucket>.json        已镜像文件 → 大小 / sha256 / md5
tools/mirror.py            同步脚本，标准库实现，无依赖
.github/workflows/         每天 03:00 (Asia/Shanghai) 自动跑
```

## 自动跟随

每天定时按分类并行：拉两个源 → 合并去重 → 比对 `state/` → 只下载缺的 → 校验 md5 → 上传 → 回写状态。md5 与目录声明不符的直接丢弃、不记入状态，下一轮重试。

12 个分类各一个 Release，最大的 `drivers` 326 个资产，低于 GitHub 单 Release 1000 个资产的上限，不需要分片。

手动：

```bash
GH_TOKEN=xxx MIRROR_REPO=owner/bannerhub-mirror \
  python3 tools/mirror.py --sync --bucket dxvk
python3 tools/mirror.py --check        # 只看差多少，不下载
python3 tools/mirror.py --manifest     # 重写 manifests/ 两份清单
```

## 边界

- 只转存 GameHub 自己能下到的文件，不聚合任何第三方源，没有本仓库自己的二进制。
- 不含客户端私有接口参数、资源或修改。`landscape-api-*.vgabc.com` 那套带签名的接口没有碰。
- 不托管游戏本体、Steam / Epic 内容、付费资源。`steam` 分类是官方目录本来就分发的客户端打包，照原样留档。
- 每个文件的权利归其上游作者。收到异议即下架对应资产。
- 本仓库自身代码为 MIT。

## 已知上游缺件

目录里列着、`Components` release 里没有的文件，逐个 URL 直连都是 404，不是本仓库的问题：

| 名称 | 目录里的文件名 | 说明 |
|---|---|---|
| `Resident Evil 3` | `Resident.Evil.3.tzst` | release 里存成了 `Resident.20Evil.203.tzst`（空格被二次编码），已按修正表取到 |
| `Torchlight II` | `Torchlight.II.tzst` | 同上，实际是 `Torchlight.20II.tzst` |
| `WRC 9` | `WRC.9.tzst` | 同上，实际是 `WRC.209.tzst` |
| `turnip_v25.2.0_R6` | `Turnip_v25.2.0_R6.tzst` | release 里只有 `Turnip_v25.2.0_R6_mem.tzst`，无后缀版确实没有 |
| `turnip_v25.2.0_R4_mem` | `turnip_v25.2.0_R4_mem.tzst` | release 里有 `R4` / `R3_mem` / `R5_mem`，独缺 `R4_mem` |

前三条已在 `upstream.json` 的 `nameFixes` 里修正。后两条等上游补，脚本每轮都会重试。
