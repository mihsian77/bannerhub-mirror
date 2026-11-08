#!/usr/bin/env python3
"""bannerhub-mirror — 把 bannerhub 组件源指向的构建同步成本仓库 Release 资产。

数据源只有 upstream.json 里那 7 个地址，不做别的猜测。
每次运行按 state/index.json 判断哪些还没镜像，按体积/数量上限分批做，下次接上。
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPSTREAM = os.path.join(ROOT, "upstream.json")
STATE_DIR = os.path.join(ROOT, "state")
CACHE = os.path.join(ROOT, ".cache")

TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
REPO = os.environ.get("MIRROR_REPO", "")
API = "https://api.github.com"
UA = "bannerhub-mirror/1.0 (+https://github.com/%s)" % (REPO or "bannerhub-mirror")

BUCKET_TITLES = {
    "box64": "Box64 / WOWBox64",
    "dxvk": "DXVK",
    "d7vk": "D7VK",
    "vkd3d": "VKD3D-Proton",
    "fex": "FEXCore",
    "wine-proton": "Wine / Proton",
    "drivers": "GPU 驱动（Adreno / Turnip）",
    "settings": "游戏配置包",
    "steam": "Steam 客户端",
    "runtime-yml": "运行库定义（yml）",
}

BUCKET_BLURB = {
    "box64": "x86_64 → ARM64 用户态转换层，含 WOWBox64 变体。",
    "dxvk": "D3D9/10/11 → Vulkan，含 async、gplasync、arm64ec 等变体。",
    "d7vk": "D3D7 → Vulkan。",
    "vkd3d": "D3D12 → Vulkan。",
    "fex": "FEXCore x86_64 → ARM64 转换层，含 arm64ec 变体。",
    "wine-proton": "Wine 容器与 Proton 构建。",
    "drivers": "Adreno / Turnip / Qualcomm 系列 GPU 驱动包。",
    "settings": "按游戏整理的运行参数包，官方目录里 type=5（Wine 容器已拆到 wine-proton）。",
    "steam": "Steam 客户端打包，官方目录里 type=7。",
    "runtime-yml": "运行库条目定义，官方目录里 type=6，每项一个 yml。",
}

FAMILY_HINTS = [
    (("box64", "wowbox64"), "Box64"),
    (("fex",), "FEXCore"),
    (("vkd3d",), "VKD3D"),
    (("d7vk",), "D7VK"),
    (("dxvk",), "DXVK"),
    (("proton",), "Proton"),
    (("wine",), "Wine"),
    (("turnip", "adreno", "qualcomm", "mesa", "freedreno", "driver"), "GpuDriver"),
]


def log(*a):
    print(*a, flush=True)


def get_json(url, retries=4):
    for i in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        if TOKEN and "api.github.com" in url:
            req.add_header("Authorization", "Bearer " + TOKEN)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            if i == retries - 1:
                raise
            log("  retry %s (%s)" % (url.rsplit("/", 1)[-1][:40], e))
            time.sleep(2 * (i + 1))


def guess_type(name, default=""):
    n = name.lower()
    for keys, t in FAMILY_HINTS:
        if any(k in n for k in keys):
            return t
    return default


def collect():
    """读 7 个源，返回去重后的条目列表。"""
    cfg = json.load(open(UPSTREAM, encoding="utf-8"))
    tmap = cfg["typeToBucket"]
    items, seen = [], set()

    def add(name, url, typ, src, bucket=None, extra=None):
        url = (url or "").strip()
        if not url.startswith("http") or url in seen:
            return
        b = bucket or tmap.get(typ)
        if not b:
            return
        seen.add(url)
        rec = {
            "bucket": b,
            "type": typ or "",
            "name": name or urllib.parse.unquote(url.rsplit("/", 1)[-1]),
            "url": url,
            "file": urllib.parse.unquote(url.rsplit("/", 1)[-1]),
            "source": src,
        }
        if extra:
            rec.update(extra)
        items.append(rec)

    for s in cfg["sources"]:
        try:
            data = get_json(s["url"])
        except Exception as e:
            log("  !! %s 拉取失败: %s" % (s["id"], e))
            continue

        if s.get("kind") == "catalog":
            raw = (data or {}).get("data", {}).get("list")
            lst = json.loads(raw) if isinstance(raw, str) else (raw or [])
            cmap = s.get("catalogBuckets", {})
            before = len(items)
            for x in lst:
                if not isinstance(x, dict):
                    continue
                typ = str(x.get("type"))
                bucket = cmap.get(typ)
                nm = (x.get("name") or "").lower()
                if typ == "1":
                    bucket = "box64" if ("box" in nm or "wow" in nm) else "fex"
                elif typ == "5" and ("wine" in nm or "proton" in nm):
                    bucket = "wine-proton"   # type 5 里混了 Wine 容器
                add(x.get("name"), x.get("download_url"), "catalog-" + typ, s["id"],
                    bucket=bucket,
                    extra={"md5": x.get("file_md5") or "",
                           "declared_size": x.get("file_size") or 0})
            log("  %-14s %4d 条（新增 %d，累计 %d）" % (s["id"], len(lst), len(items) - before, len(items)))
            continue

        if not isinstance(data, list):
            continue
        for x in data:
            if not isinstance(x, dict):
                continue
            add(x.get("verName") or x.get("name"), x.get("remoteUrl") or x.get("url"),
                x.get("type") or "", s["id"])
        log("  %-14s %4d 条（累计 %d）" % (s["id"], len(data), len(items)))
    return items


def state_path(bucket):
    return os.path.join(STATE_DIR, "%s.json" % (bucket or "all"))


def load_state(bucket):
    p = state_path(bucket)
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return {"mirrored": {}}


def save_state(st, bucket):
    st["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(state_path(bucket), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1, sort_keys=True)


def api(method, path, payload=None, raw=False):
    url = path if path.startswith("http") else API + path
    data = json.dumps(payload).encode() if payload is not None else None
    for i in range(4):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Bearer " + TOKEN)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", UA)
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read()
                return json.loads(body) if body and not raw else body
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and i < 3:
                time.sleep(3)
                continue
            raise SystemExit("HTTP %s %s %s\n%s" % (e.code, method, path, e.read()[:300].decode()))
        except Exception as e:
            if i == 3:
                raise
            time.sleep(3)


def release_by_tag(tag):
    try:
        return api("GET", "/repos/%s/releases/tags/%s" % (REPO, tag))
    except SystemExit:
        return None


MAX_ASSETS = 1000  # GitHub 单个 release 的资产上限


def shard_tag(bucket, i):
    return bucket if i == 1 else "%s-%d" % (bucket, i)


def ensure_release(tag):
    rel = release_by_tag(tag)
    if rel:
        return rel
    base = tag.split("-")[0] if tag.rsplit("-", 1)[-1].isdigit() else tag
    title = BUCKET_TITLES.get(base, base)
    if tag != base:
        title += " (%s)" % tag.rsplit("-", 1)[-1]
    rel = api("POST", "/repos/%s/releases" % REPO, {
        "tag_name": tag,
        "name": "%s · 镜像" % title,
        "body": "%s\n\n内容来自 bannerhub-revanced 所索引的上游项目，本仓库仅做保留备份。"
                % BUCKET_BLURB.get(base, ""),
        "draft": False,
        "prerelease": False,
    })
    log("  新建 release: %s" % tag)
    return rel


def ensure_shard(bucket):
    """返回第一个未满 1000 个资产的分片。"""
    i = 1
    while True:
        tag = shard_tag(bucket, i)
        rel = ensure_release(tag)
        have = assets_of(rel)
        if len(have) < MAX_ASSETS:
            return tag, rel, have
        log("  %s 已满 %d，改用 %s" % (tag, MAX_ASSETS, shard_tag(bucket, i + 1)))
        i += 1


def assets_of(rel):
    out, page = {}, 1
    while True:
        batch = api("GET", "/repos/%s/releases/%d/assets?per_page=100&page=%d" % (REPO, rel["id"], page))
        if not batch:
            break
        for a in batch:
            out[a["name"]] = a
        if len(batch) < 100:
            break
        page += 1
    return out


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, 1024 * 256)


def digests_of(path):
    h1, h2 = hashlib.sha256(), hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 512), b""):
            h1.update(chunk)
            h2.update(chunk)
    return h1.hexdigest(), h2.hexdigest()


def upload(rel, path, name):
    size = os.path.getsize(path)
    q = urllib.parse.urlencode({"name": name})
    url = "https://uploads.github.com/repos/%s/releases/%d/assets?%s" % (REPO, rel["id"], q)
    with open(path, "rb") as f:
        data = f.read()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Content-Type", "application/octet-stream")
    req.add_header("Content-Length", str(size))
    req.add_header("User-Agent", UA)
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", action="store_true", help="下载并上传缺失资产")
    ap.add_argument("--check", action="store_true", help="只对比，不下载")
    ap.add_argument("--max-gb", type=float, default=3.0, help="单次下载体积上限")
    ap.add_argument("--max-files", type=int, default=400, help="单次文件数上限")
    ap.add_argument("--bucket", default="", help="只处理某个分类")
    a = ap.parse_args()

    if not REPO or not TOKEN:
        raise SystemExit("需要 MIRROR_REPO 与 GH_TOKEN")

    log("== 采集上游清单")
    items = collect()
    if a.bucket:
        items = [i for i in items if i["bucket"] == a.bucket]
    log("合计 %d 条" % len(items))

    st = load_state(a.bucket)
    mirrored = st.get("mirrored", {})
    pending = [i for i in items if i["url"] not in mirrored]
    log("已镜像 %d / 待处理 %d" % (len(items) - len(pending), len(pending)))

    if a.check or not a.sync:
        import collections
        c = collections.Counter(i["bucket"] for i in pending)
        for k, v in c.most_common():
            log("  待补 %-12s %d" % (k, v))
        return

    os.makedirs(CACHE, exist_ok=True)
    done = bytes_ = 0

    # 按分类分组，避免反复打开 release
    by_bucket = {}
    for it in pending:
        by_bucket.setdefault(it["bucket"], []).append(it)

    for bucket, group in sorted(by_bucket.items(), key=lambda kv: -len(kv[1])):
        tag, rel, have = ensure_shard(bucket)
        for it in group:
            if done >= a.max_files or bytes_ >= a.max_gb * 1e9:
                log("== 达到单次上限，剩余留到下次")
                save_state(st, a.bucket)
                return
            name = it["file"]
            if name in have:
                mirrored[it["url"]] = {"bucket": tag, "asset": name,
                                       "size": have[name]["size"], "sha256": "",
                                       "mtime": have[name].get("updated_at", "")}
                continue
            tmp = os.path.join(CACHE, name)
            try:
                download(it["url"], tmp)
            except Exception as e:
                log("  下载失败 %s (%s)" % (name[:60], e))
                continue
            size = os.path.getsize(tmp)
            if size == 0:
                os.remove(tmp)
                continue
            if len(have) >= MAX_ASSETS:
                tag, rel, have = ensure_shard(bucket)
            digest, md5 = digests_of(tmp)
            if it.get("md5") and md5.lower() != it["md5"].lower():
                log("  md5 不符，丢弃 %s（期望 %s 实得 %s）" % (name[:50], it["md5"][:8], md5[:8]))
                os.remove(tmp)
                continue
            try:
                up = upload(rel, tmp, name)
            except Exception as e:
                log("  上传失败 %s (%s)" % (name[:60], e))
                os.remove(tmp)
                continue
            have[name] = up
            mirrored[it["url"]] = {"bucket": tag, "asset": name, "size": size,
                                   "sha256": digest, "md5": md5,
                                   "source": it.get("source", ""),
                                   "mtime": up.get("updated_at", "")}
            done += 1
            bytes_ += size
            log("  [%d] %-14s %7.1f MB  %s" % (done, tag, size / 1e6, name[:60]))
            os.remove(tmp)
            if done % 20 == 0:
                st["mirrored"] = mirrored
                save_state(st, a.bucket)
        st["mirrored"] = mirrored
        save_state(st, a.bucket)

    log("== 本轮 %d 个，%.2f GB" % (done, bytes_ / 1e9))


if __name__ == "__main__":
    main()
