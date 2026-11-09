#!/usr/bin/env python3
"""bannerhub-mirror — 把 GameHub 官方组件目录里的文件同步成本仓库 Release 资产。

数据源只有 upstream.json 里那一个地址：getAllComponentList。
不在那份目录里的东西，一个都不镜像——这条是硬约束，不是默认值。
每次运行按 state/<bucket>.json 判断哪些还没镜像，按体积/数量上限分批做，下次接上。
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
    "box64": "Box64",
    "dxvk": "DXVK",
    "vkd3d": "VKD3D-Proton",
    "fex": "FEXCore",
    "drivers": "GPU 驱动",
    "settings": "游戏配置包与 Wine 容器",
    "steam": "Steam 客户端",
    "runtime-yml": "运行库定义（yml）",
}

BUCKET_BLURB = {
    "box64": "GameHub 目录 type=1 中 Box64 系列，共 13 条。",
    "fex": "GameHub 目录 type=1 中 FEXCore 系列，共 31 条。",
    "dxvk": "GameHub 目录 type=3 整体，共 68 条。",
    "vkd3d": "GameHub 目录 type=4 整体，共 11 条。",
    "drivers": "GameHub 目录 type=2 整体，共 323 条，Adreno / Turnip / Qualcomm 驱动包。",
    "settings": "GameHub 目录 type=5 整体，共 70 条：游戏配置包与 Wine / Proton 容器。",
    "steam": "GameHub 目录 type=7 整体，共 3 条。",
    "runtime-yml": "GameHub 目录 type=6 整体，共 121 条，每项一个运行库定义 yml。",
}


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
    """读官方目录，返回去重后的条目列表。非 catalog 源一律忽略。"""
    cfg = json.load(open(UPSTREAM, encoding="utf-8"))
    items, seen = [], set()

    for s in cfg["sources"]:
        if s.get("kind") != "catalog":
            log("  !! 跳过非官方源 %s（本仓库只镜像 GameHub 目录内的文件）" % s["id"])
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
            if typ == "1":  # 转换层里混着 Box64 和 FEXCore，按名字分
                bucket = "box64" if "box" in (x.get("name") or "").lower() else "fex"
            if not bucket:
                continue
            url = (x.get("download_url") or "").strip()
            if not url.startswith("http") or url in seen:
                continue
            seen.add(url)
            fname = urllib.parse.unquote(url.rsplit("/", 1)[-1])
            items.append({
                "bucket": bucket,
                "type": "catalog-" + typ,
                "name": x.get("name") or fname,
                "display": x.get("display_name") or x.get("name") or fname,
                "ver": x.get("version") or "",
                "id": x.get("id"),
                "url": url,
                "file": fname,
                "source": s["id"],
                "md5": x.get("file_md5") or "",
                "declared_size": x.get("file_size") or 0,
            })
        log("  %-14s %4d 条（新增 %d，累计 %d）" % (s["id"], len(lst), len(items) - before, len(items)))
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
    order = ["drivers", "box64", "fex", "dxvk", "vkd3d", "settings", "runtime-yml", "steam"]
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
            "file": it["file"], "size": it.get("declared_size", 0),
            "md5": it["md5"], "url": it["url"],
        })
    json.dump(doc, open(os.path.join(ROOT, "manifests", "catalog.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    md = ["# GameHub 官方组件清单", "",
          "来源：`getAllComponentList`（%s）" % doc["source"], "",
          "共 **%d** 个文件，合计 **%.2f GB**。本表由 `tools/mirror.py --manifest` 生成，不要手改。"
          % (doc["total"], doc["totalBytes"] / 1e9), "",
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
               "| 名称 | 版本 | 文件 | 大小 |", "| --- | --- | --- | ---: |"]
        for i in sorted(rows, key=lambda x: (x["name"] or "").lower()):
            md.append("| %s | %s | `%s` | %.1f MB |"
                      % (i["display"], i["version"], i["file"], i["size"] / 1e6))
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

    log("== 采集官方目录")
    items = collect()
    if a.bucket:
        items = [i for i in items if i["bucket"] == a.bucket]
    log("合计 %d 个文件，%.2f GB"
        % (len(items), sum(i.get("declared_size", 0) for i in items) / 1e9))

    if a.manifest:
        write_manifest(collect())
        return

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
