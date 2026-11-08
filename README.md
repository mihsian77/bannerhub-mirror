# bannerhub-mirror

`bannerhub-revanced` 所索引的组件构建，在这里留一份。

组件项目的构建产物长期挂在个人 GitHub Release 下，删库、改 tag、清资产都发生过。这个仓库不做别的事：**按上游清单把文件取过来，贴上校验值，按类别放好**。下游（Android 上的 Windows 兼容层 / 容器类应用）可以直接从这里取，不必担心某天上游没了。

## 数据源

全部来自 `bannerhub-revanced` 的 `BhComponentRepo.REPOS`，原样转录在 [`upstream.json`](upstream.json)，脚本只认这一份文件。

| 源 | 提供 |
|---|---|
| [Arihany/WinlatorWCPHub](https://github.com/Arihany/WinlatorWCPHub) | DXVK / VKD3D-Proton / FEXCore 的 `.wcp` |
| [The412Banner/Nightlies](https://github.com/The412Banner/Nightlies) | Box64 / FEX / DXVK / VKD3D / D7VK / Wine / Proton 全量构建 |
| Kimchi / StevenMXZ / MTR / Whitebelyash | Adreno / Turnip 驱动 zip |
| [bannerhub-api 目录](https://the412banner.github.io/bannerhub-api/simulator/v2/getAllComponentList) | 整理后的组件目录，每条带 `file_md5` / `file_size` / 下载地址 |

## 分类

| Release | 内容 |
|---|---|
| [`box64`](../../releases/tag/box64) | Box64 与 WOWBox64 |
| [`fex`](../../releases/tag/fex) | FEXCore |
| [`dxvk`](../../releases/tag/dxvk) | DXVK（含 async / gplasync / arm64ec 变体） |
| [`vkd3d`](../../releases/tag/vkd3d) | VKD3D-Proton |
| [`d7vk`](../../releases/tag/d7vk) | D7VK |
| [`wine-proton`](../../releases/tag/wine-proton) | Wine 容器与 Proton |
| [`drivers`](../../releases/tag/drivers) | Adreno / Turnip / Qualcomm 驱动 |
| [`settings`](../../releases/tag/settings) | 官方目录 type=5：60 个游戏配置包 + 10 个 Wine / Proton 容器 |
| [`steam`](../../releases/tag/steam) | Steam 客户端打包 |
| [`runtime-yml`](../../releases/tag/runtime-yml) | 运行库条目定义，每项一个 yml |

单目录 640 条实测 4.07 GB，其中配置包与驱动各占 1 GB 以上；社区源再补 1504 条、8.59 GB。

直链形如：

```
https://github.com/<owner>/bannerhub-mirror/releases/download/dxvk/DXVK-v2.7.1.zip
```

`tag` 固定，文件只增不删，所以 URL 可以硬编码。

## 目录

```
upstream.json          七个源 + 类型到分类的映射
manifests/*.json       各分类的条目清单（名称 / 上游地址 / 校验值）
state/<bucket>.json    已镜像文件 → 大小 / sha256 / 资产名
tools/mirror.py        同步脚本，标准库实现，无依赖
.github/workflows/     每天 03:00 (Asia/Shanghai) 自动跑
```

## 自动跟随

每天定时任务按分类并行拉取：比对 `state/<bucket>.json` → 只下载缺失的 → 上传到对应 Release → 回写状态。单分类上限 12 GB / 3000 个文件，超出的下一轮继续，不会半途丢进度。

GitHub 对单个 Release 的资产数上限是 1000，分类超过这个数会自动开 `drivers-2`、`drivers-3` 这样的分片，`state` 里记的是实际落到的 tag。

首次全量约 2100 个文件、12 GB。GitHub 对短时间内的批量上传有风控，超过一定量会返回 403，脚本会跳过并在下一轮补 —— 所以第一次跑完可能需要两三天才真正齐，之后每天只增量几条，不会再触发。

手动触发：

```bash
GH_TOKEN=xxx MIRROR_REPO=owner/bannerhub-mirror \
  python3 tools/mirror.py --sync --bucket dxvk --max-gb 12
python3 tools/mirror.py --check        # 只看差多少，不下载
```

## 边界

- 只转存**上游公开发布**的构建产物，仓库里没有本仓库自己的二进制。
- 不含任何客户端软件的私有文件、资源或接口参数；不涉及对任何客户端的修改。
- 不托管游戏本体、Steam / Epic 内容、付费资源。
- 每个文件的权利归其上游作者。本仓库只做保留备份与分发，遇到作者异议即下架对应资产。
- 本仓库自身代码为 MIT。

> 上游清单本身可能滞后于真实发布。`manifests/` 里的条目数是镜像启动时的快照，`state/` 才是实际已备到的文件。
>
> 已知上游缺文件：`Resident Evil 3`、`Torchlight II`、`WRC 9` 三条约目录里有、`bannerhub-api` 的 release 里没有，两种文件名写法都是 404。补不了，等上游自己修。
