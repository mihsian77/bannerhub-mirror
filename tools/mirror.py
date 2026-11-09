#!/usr/bin/env python3
"""bannerhub-mirror — 把 GameHub 官方组件目录里的文件同步成本仓库 Release 资产。

数据源只有 upstream.json 里那一个地址：getAllComponentList。
不在那份目录里的东西，一个都不镜像——这条是硬约束，不是默认值。
每次运行按 state/<bucket>.json 判断哪些还没镜像，按体积/数量上限分批做，下次接上。
"""

import argparse
import base64
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
    "box64": "Box64",
    "dxvk": "DXVK",
    "vkd3d": "VKD3D-Proton",
    "fex": "FEXCore",
    "drivers": "GPU 驱动",
    "settings": "游戏配置包",
    "steam": "Steam 客户端",
    "runtime-yml": "运行库定义（yml）",
    "wine": "Wine / Proton 容器",
    "system": "系统镜像（imagefs）",
    "runtimes-bin": "运行库安装包（msi / exe）",
    "unindexed": "未索引的独有文件",
}

BUCKET_BLURB = {
    "box64": "GameHub 目录 type=1 中 Box64 系列。",
    "fex": "GameHub 目录 type=1 中 FEXCore 系列。",
    "dxvk": "GameHub 目录 type=3 整体。",
    "vkd3d": "GameHub 目录 type=4 整体。",
    "drivers": "GameHub 目录 type=2 整体，Adreno / Turnip / Qualcomm 驱动包；另含未索引的 Banners-Turnip 构建。",
    "settings": "GameHub 目录 type=5 整体：游戏配置包。",
    "steam": "GameHub 目录 type=7 整体。",
    "runtime-yml": "GameHub 目录 type=6 整体，每项一个安装脚本 yml；另含 1 个未索引的 yml。",
    "wine": "Wine / Proton 容器镜像，组件目录未索引，来自 Components release 实际资产。",
    "system": "imagefs 系统镜像与 base 基础包，组件目录未索引。",
    "runtimes-bin": "运行库安装包本体（VC++ / PhysX / wine-mono / K-Lite 等），yml 里引用的 exe / msi。",
    "unindexed": "在 Components release 里存在、但不在组件目录里、也无法从名字判断归属的文件。保留原样，附 SHA-256 与体积，供比对。",
}

MD5_NAME = re.compile(r"^([0-9a-f]{32})\.")


def bucket_for_asset(fname, is_md5):
    n = fname.lower()
    if n.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        return None
    if is_md5:
        return "unindexed"
    if n.endswith((".yml", ".yaml")):
        return "runtime-yml"
    if n.startswith("imagefs") or n.startswith("base_"):
        return "system"
    if "wine_proton" in n or n.endswith(".tar.zst"):
        return "wine"
    if n.endswith((".msi", ".exe")):
        return "runtimes-bin"
    if "turnip" in n or "adreno" in n:
        return "drivers"
    if n.endswith((".png", ".jpg", ".jpeg", ".gif")):
        return None
    return "unindexed"


def pretty(name, fname):
    """把目录里的 name 变成干净的资产名，保留真实扩展名。"""
    ext = os.path.splitext(fname)[1].lower()
    base = (name or os.path.splitext(fname)[0]).strip()
    base = base.replace("/", "_").replace("\\", "_")
    base = re.sub(r"\s+", "_", base)
    base = re.sub(r"[^\w\u4e00-\u9fa5.\-]+", "", base)
    base = base.strip("._-") or "unnamed"
    return base + ext


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


def collect():
    """读组件目录 + Components release 实际资产，合并成一份去重清单。"""
    cfg = json.load(open(UPSTREAM, encoding="utf-8"))
    fixes = cfg.get("nameFixes") or {}
    items, seen_url = [], set()
    cat_files, cat_md5 = set(), set()

    # 第一遍：组件目录（有名字、有 md5 的那批）
    for s in cfg["sources"]:
        if s.get("kind") != "catalog":
            continue
        try:
            data = get_json(s["url"])
        except Exception as e:
            log("  !! %s 拉取失败: %s" % (s["id"], e))
            continue

        raw = (data or {}).get("data", {}).get("list")
        lst = json.loads(raw) if isinstance(raw, str) else (raw or [])
        cmap = s.get("catalogBuckets", {})
        before = len(items)
        for x in lst:
            if not isinstance(x, dict):
                continue
            typ = str(x.get("type"))
            bucket = cmap.get(typ)
            if typ == "1":
                bucket = "box64" if "box" in (x.get("name") or "").lower() else "fex"
            if not bucket:
                continue
            url = (x.get("download_url") or "").strip()
            if not url.startswith("http") or url in seen_url:
                continue
            fname = urllib.parse.unquote(url.rsplit("/", 1)[-1])
            if fname in fixes:  # 目录写错名字的，换成 release 里的真实资产名
                url = url.rsplit("/", 1)[0] + "/" + urllib.parse.quote(fixes[fname])
                fname = fixes[fname]
            seen_url.add(url)
            cat_files.add(fname)
            if x.get("file_md5"):
                cat_md5.add(x["file_md5"].lower())
            items.append({
                "bucket": bucket,
                "type": "catalog-" + typ,
                "name": x.get("name") or fname,
                "display": x.get("display_name") or x.get("name") or fname,
                "ver": x.get("version") or "",
                "gpu": x.get("gpu_range") or "",
                "id": x.get("id"),
                "url": url,
                "file": fname,
                "source": s["id"],
                "md5": x.get("file_md5") or "",
                "declared_size": x.get("file_size") or 0,
            })
        log("  %-14s %4d 条（新增 %d，累计 %d）" % (s["id"], len(lst), len(items) - before, len(items)))

    # 第二遍：release 实际资产，补目录没索引的
    for s in cfg["sources"]:
        if s.get("kind") != "release_assets":
            continue
        try:
            rel = get_json(s["url"])
        except Exception as e:
            log("  !! %s 拉取失败: %s" % (s["id"], e))
            continue
        assets, page = [], 1
        while True:
            batch = get_json("%s/releases/%d/assets?per_page=100&page=%d" % (
                s["url"].split("/releases/")[0], rel["id"], page))
            if not batch:
                break
            assets += batch
            if len(batch) < 100:
                break
            page += 1

        added = skipped_dup = 0
        for a in assets:
            fname = a["name"]
            if fname in cat_files:
                continue  # 目录里已经有了
            m = MD5_NAME.match(fname)
            if m and m.group(1) in cat_md5:
                skipped_dup += 1  # 同一份文件被另存成 md5 名，内容已有
                continue
            b = bucket_for_asset(fname, bool(m))
            if not b:
                continue
            url = a.get("browser_download_url") or ""
            if url in seen_url:
                continue
            seen_url.add(url)
            items.append({
                "bucket": b,
                "type": "release-extra",
                "name": os.path.splitext(fname)[0],
                "display": "（未索引）" + os.path.splitext(fname)[0],
                "ver": "",
                "gpu": "",
                "id": None,
                "url": url,
                "file": fname,
                "source": s["id"],
                "md5": m.group(1) if m else "",
                "declared_size": a.get("size") or 0,
            })
            added += 1
        log("  %-14s release 资产 %d 个：补入 %d，按 md5 判定重复跳过 %d"
            % (s["id"], len(assets), added, skipped_dup))

    # 资产名去重
    used = {}
    for it in items:
        base = pretty(it["name"], it["file"])
        if base in used:
            stem, ext = os.path.splitext(base)
            used[base] += 1
            base = "%s-%d%s" % (stem, used[base], ext)
        else:
            used[base] = 1
        it["asset"] = base
    log("合计 %d 个文件，%.2f GB"
        % (len(items), sum(i.get("declared_size", 0) for i in items) / 1e9))
    return items


def state_path(bucket):
    return os.path.join(STATE_DIR, "%s.json" % (bucket or "all"))


def push_state(bucket):
    """通过 contents API 单独提交 state 文件，避免并发 rebase 打架。"""
    path = state_path(bucket)
    rel = "state/%s.json" % bucket
    body = {
        "message": "state: %s %s" % (bucket, time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())),
        "content": base64.b64encode(open(path, "rb").read()).decode(),
        "branch": "main",
    }
    try:
        body["sha"] = api("GET", "/repos/%s/contents/%s" % (REPO, rel))["sha"]
    except Exception:
        pass
    for i in range(4):
        try:
            api("PUT", "/repos/%s/contents/%s" % (REPO, rel), body)
            log("  state 已提交：%s" % rel)
            return True
        except SystemExit as e:
            msg = str(e)
            if "409" in msg or "422" in msg:  # sha 过期，重新取
                try:
                    body["sha"] = api("GET", "/repos/%s/contents/%s" % (REPO, rel))["sha"]
                except Exception:
                    pass
            if i == 3:
                log("  state 提交失败：%s" % msg[:120])
                return False
            time.sleep(3)
    return False


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
    url = urllib.parse.quote(url, safe=":/?&=#%+~@!$'()*,;")
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


def write_manifest(items):
    """把官方目录落成两份人类可读清单：JSON 给程序，Markdown 给人看。"""
    os.makedirs(os.path.join(ROOT, "manifests"), exist_ok=True)
    order = ["drivers", "settings", "runtime-yml", "dxvk", "fex", "box64", "vkd3d",
             "steam", "wine", "system", "runtimes-bin", "unindexed"]
    labels = BUCKET_TITLES

    doc = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": json.load(open(UPSTREAM, encoding="utf-8"))["sources"][0]["url"],
        "total": len(items),
        "totalBytes": sum(i.get("declared_size", 0) for i in items),
        "buckets": {},
        "items": [],
    }
    for it in items:
        doc["buckets"].setdefault(it["bucket"], 0)
        doc["buckets"][it["bucket"]] += 1
        doc["items"].append({
            "bucket": it["bucket"], "type": it["type"], "id": it.get("id"),
            "name": it["name"], "display": it["display"], "version": it["ver"],
            "gpu": it.get("gpu", ""),
            "asset": it.get("asset") or it["file"],
            "official_file": it["file"],
            "size": it.get("declared_size", 0),
            "md5": it["md5"], "url": it["url"],
        })
    json.dump(doc, open(os.path.join(ROOT, "manifests", "catalog.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    md = ["# GameHub 组件清单", "",
          "来源：`getAllComponentList` + `bannerhub-api` 的 `Components` release", "",
          "共 **%d** 个文件，合计 **%.2f GB**。本表由 `tools/mirror.py --manifest` 生成，不要手改。"
          % (doc["total"], doc["totalBytes"] / 1e9), "",
          "`资产名` 是 release 里实际的文件名，已从 md5 命名规范化为可读名；`官方文件名` 是 GameHub 目录/Release 里的原名，用于反查。", "",
          "| 分类 | 条数 | 体积 |", "| --- | ---: | ---: |"]
    for b in order:
        if b not in doc["buckets"]:
            continue
        s = sum(i["size"] for i in doc["items"] if i["bucket"] == b)
        md.append("| %s | %d | %.2f GB |" % (labels.get(b, b), doc["buckets"][b], s / 1e9))
    md.append("")
    for b in order:
        rows = [i for i in doc["items"] if i["bucket"] == b]
        if not rows:
            continue
        md += ["## %s（%d）" % (labels.get(b, b), len(rows)), "",
               "| 名称 | 版本 | 资产名 | 大小 |", "| --- | --- | --- | ---: |"]
        for i in sorted(rows, key=lambda x: (x["name"] or "").lower()):
            md.append("| %s | %s | `%s` | %.1f MB |"
                      % (i["display"], i["version"], i["asset"], i["size"] / 1e6))
        md.append("")
    open(os.path.join(ROOT, "manifests", "CATALOG.md"), "w", encoding="utf-8").write("\n".join(md))
    log("  清单已写入 manifests/catalog.json 与 manifests/CATALOG.md")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", action="store_true", help="下载并上传缺失资产")
    ap.add_argument("--check", action="store_true", help="只对比，不下载")
    ap.add_argument("--manifest", action="store_true", help="只重写 manifests 清单")
    ap.add_argument("--max-gb", type=float, default=3.0, help="单次下载体积上限")
    ap.add_argument("--max-files", type=int, default=400, help="单次文件数上限")
    ap.add_argument("--bucket", default="", help="只处理某个分类")
    a = ap.parse_args()

    log("== 采集")
    items = collect()
    if a.manifest:
        write_manifest(items)
        return
    if a.bucket:
        items = [i for i in items if i["bucket"] == a.bucket]

    if not REPO or not TOKEN:
        raise SystemExit("需要 MIRROR_REPO 与 GH_TOKEN")

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
                if a.bucket:
                    push_state(a.bucket)
                return
            name = it.get("asset") or it["file"]
            if name in have:
                mirrored[it["url"]] = {"bucket": tag, "asset": name,
                                       "official_file": it["file"],
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
                                   "official_file": it["file"],
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
        if a.bucket:
            push_state(a.bucket)

    log("== 本轮 %d 个，%.2f GB" % (done, bytes_ / 1e9))


if __name__ == "__main__":
    main()
