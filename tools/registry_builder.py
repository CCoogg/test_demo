#!/usr/bin/env python3
"""
registry_builder.py

从 csv_runner.py 输出的 JSONL 中提取 locator_candidate，
生成/更新 test_reading_framework/locators/locator_registry.py。

Usage:
    python tools/registry_builder.py \
        --outputs outputs/ \
        --registry ../../test_reading_framework/locators/locator_registry.py \
        [--min-confidence 0.6] \
        [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# JSONL 读取
# ---------------------------------------------------------------------------

def iter_records(outputs_dir: Path):
    """逐条 yield JSONL records，跳过损坏行。"""
    for jsonl_file in sorted(outputs_dir.glob("*.jsonl")):
        with open(jsonl_file, encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"[warn] {jsonl_file.name}:{lineno} JSON parse error: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# locator_key 生成
# ---------------------------------------------------------------------------

def _normalize_resource_id(rid: str) -> str:
    """com.example.readingapp:id/reader_content → reader_content"""
    if "/" in rid:
        rid = rid.split("/")[-1]
    return rid


def _to_key(raw: str) -> str:
    """将任意字符串转为 UPPER_SNAKE 格式的 locator_key。"""
    raw = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", raw)
    raw = raw.strip("_")
    # 中文转拼音太重，直接用 unicode 占位保留语义
    # 全大写 + 下划线
    return raw.upper()


def suggest_key(element_snapshot: Dict[str, Any], strategies: List[Dict[str, str]]) -> str:
    """
    从 element_snapshot / strategies 推断 locator_key。
    优先级：resourceId > contentDesc > text > class
    """
    rid = (element_snapshot.get("resourceId") or "").strip()
    if rid:
        return _to_key(_normalize_resource_id(rid))

    cdesc = (element_snapshot.get("contentDesc") or "").strip()
    if cdesc:
        return _to_key(cdesc)

    text = (element_snapshot.get("text") or "").strip()
    if text:
        return _to_key(text)

    # 从 strategies 里找 id / text
    for s in strategies:
        if s.get("by") == "id":
            return _to_key(_normalize_resource_id(s["value"]))
        if s.get("by") in ("text", "content_desc"):
            return _to_key(s["value"])

    cls = (element_snapshot.get("class") or "").strip()
    if cls:
        short = cls.split(".")[-1]
        return _to_key(short)

    return "UNKNOWN_ELEMENT"


def make_description(element_snapshot: Dict[str, Any], case_title: str) -> str:
    """生成 description 字段（人工后续可编辑）。"""
    parts = []
    text = (element_snapshot.get("text") or "").strip()
    cdesc = (element_snapshot.get("contentDesc") or "").strip()
    rid = (element_snapshot.get("resourceId") or "").strip()
    cls = (element_snapshot.get("class") or "").strip().split(".")[-1]
    if text:
        parts.append(f'"{text}"')
    if cdesc:
        parts.append(f'desc={cdesc}')
    if rid:
        parts.append(f'id={rid}')
    parts.append(cls)
    parts.append(f"[来源:{case_title}]")
    return " / ".join(parts)


# ---------------------------------------------------------------------------
# 主键（去重用）
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)


def _is_stable_id(value: str) -> bool:
    """UUID 或纯数字后缀的 resource-id 不稳定，排除。"""
    if _UUID_RE.search(value):
        return False
    # 形如 item_12345 这类含纯数字后缀（动态列表项）也排除
    if re.search(r"_\d{4,}$", value):
        return False
    return True


def primary_key(strategies: List[Dict[str, str]]) -> Optional[str]:
    """
    用 resourceId 作为去重主键。
    UUID / 动态 id 不稳定，跳过，降级用 text 或 content_desc。
    """
    for s in strategies:
        if s.get("by") == "id" and _is_stable_id(s["value"]):
            return f"id:{s['value']}"
    for s in strategies:
        if s.get("by") == "content_desc":
            return f"cdesc:{s['value']}"
    for s in strategies:
        if s.get("by") == "text":
            return f"text:{s['value']}"
    return None


# ---------------------------------------------------------------------------
# 从 JSONL 提取候选
# ---------------------------------------------------------------------------

def collect_candidates(
    outputs_dir: Path,
    min_confidence: float,
) -> Dict[str, Dict[str, Any]]:
    """
    返回 { primary_key → candidate_entry } 去重后的候选集合。
    candidate_entry = {
        "suggested_key": str,
        "description": str,
        "locators": [...],
        "confidence": float,
    }
    若同一 primary_key 出现多次，保留 confidence 最高的那条。
    """
    seen: Dict[str, Dict[str, Any]] = {}

    for record in iter_records(outputs_dir):
        case_title = record.get("case_meta", {}).get("title", "unknown")
        for obs in record.get("observations", []):
            candidate = obs.get("locator_candidate")
            if not candidate:
                continue
            confidence = float(candidate.get("confidence", 0))
            if confidence < min_confidence:
                continue
            strategies = candidate.get("strategies") or []
            if not strategies:
                continue
            element_snapshot = obs.get("element_snapshot") or {}

            pk = primary_key(strategies)
            if pk is None:
                continue

            if pk in seen and seen[pk]["confidence"] >= confidence:
                continue

            suggested = suggest_key(element_snapshot, strategies)
            desc = make_description(element_snapshot, case_title)

            seen[pk] = {
                "suggested_key": suggested,
                "description": desc,
                "locators": strategies,
                "confidence": confidence,
            }

    return seen


# ---------------------------------------------------------------------------
# 读取现有 registry（保留人工审核过的条目）
# ---------------------------------------------------------------------------

def load_existing_keys(registry_path: Path) -> set[str]:
    """返回现有 registry 中已有的 locator_key 集合。"""
    if not registry_path.exists():
        return set()
    keys: set[str] = set()
    with open(registry_path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r'\s+"([A-Z][A-Z0-9_]+)"\s*:', line)
            if m:
                keys.add(m.group(1))
    return keys


# ---------------------------------------------------------------------------
# 生成 Python 代码
# ---------------------------------------------------------------------------

def _locators_repr(locators: List[Dict[str, str]]) -> str:
    parts = []
    for loc in locators:
        by = loc.get("by", "")
        value = loc.get("value", "").replace("'", "\\'")
        parts.append(f'{{"by": "{by}", "value": \'{value}\'}}')
    inner = ",\n            ".join(parts)
    return f"[\n            {inner},\n        ]"


def render_registry(entries: Dict[str, Dict[str, Any]]) -> str:
    """将 entries 渲染为完整的 locator_registry.py 内容。"""
    lines = [
        "from __future__ import annotations",
        "",
        "from typing import Any, Dict, List",
        "",
        "",
        "LOCATOR_REGISTRY: Dict[str, Dict[str, Any]] = {",
    ]
    for key, entry in sorted(entries.items()):
        desc = entry["description"].replace('"', '\\"')
        locators_str = _locators_repr(entry["locators"])
        lines.append(f'    "{key}": {{')
        lines.append(f'        "description": "{desc}",')
        lines.append(f'        "locators": {locators_str},')
        lines.append(f'    }},')
    lines += [
        "}",
        "",
        "",
        "def get_locator_list(locator_key: str) -> List[Dict[str, str]]:",
        '    meta = LOCATOR_REGISTRY.get(locator_key)',
        '    if not meta:',
        '        return []',
        '    locators = meta.get("locators", [])',
        '    return list(locators) if isinstance(locators, list) else []',
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 合并逻辑：新增条目 + 保留已有条目
# ---------------------------------------------------------------------------

def merge_into_registry(
    registry_path: Path,
    new_candidates: Dict[str, Dict[str, Any]],
    dry_run: bool,
) -> Tuple[int, int]:
    """
    将新候选合并进现有 registry。
    - 已有 locator_key 不覆盖（人工审核优先）
    - 新 key 直接追加
    返回 (added, skipped)。
    """
    existing_keys = load_existing_keys(registry_path)

    # 读取现有 registry 的完整内容（保留）
    existing_content = ""
    if registry_path.exists():
        with open(registry_path, encoding="utf-8") as f:
            existing_content = f.read()

    # 找出新条目（key 不冲突）
    to_add: Dict[str, Dict[str, Any]] = {}
    skipped = 0
    for pk, entry in new_candidates.items():
        key = entry["suggested_key"]
        if key in existing_keys:
            print(f"[skip] '{key}' already in registry (primary_key={pk})")
            skipped += 1
        else:
            # key 冲突：在建议名后加数字后缀
            base = key
            suffix = 2
            while key in existing_keys or key in {e["suggested_key"] for e in to_add.values()}:
                key = f"{base}_{suffix}"
                suffix += 1
            entry = dict(entry, suggested_key=key)
            to_add[key] = entry

    added = len(to_add)
    if not to_add:
        print("[info] 无新条目需要写入。")
        return added, skipped

    if dry_run:
        print(f"[dry-run] 将新增 {added} 条（以下为预览）：")
        for key, entry in sorted(to_add.items()):
            print(f"  {key}  confidence={entry['confidence']:.2f}  desc={entry['description'][:60]}")
        return added, skipped

    # 将新条目追加到现有文件末尾的 LOCATOR_REGISTRY 内（插入到最后一个 "}" 前）
    # 简单策略：重新生成整个文件
    # 先解析现有 registry（如果有的话），合并后重新渲染
    all_entries: Dict[str, Dict[str, Any]] = {}

    # 从现有文件中提取已有条目（保守：只保留 key + locators + description）
    if registry_path.exists():
        all_entries.update(_parse_existing_registry(registry_path))

    # 追加新条目
    all_entries.update(to_add)

    new_content = render_registry(all_entries)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with open(registry_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[done] 写入 {registry_path}，新增 {added} 条，跳过 {skipped} 条。")
    return added, skipped


def _parse_existing_registry(registry_path: Path) -> Dict[str, Dict[str, Any]]:
    """
    从现有 locator_registry.py 中解析条目。
    使用 exec 执行文件，提取 LOCATOR_REGISTRY 变量。
    """
    namespace: Dict[str, Any] = {}
    try:
        with open(registry_path, encoding="utf-8") as f:
            source = f.read()
        exec(compile(source, str(registry_path), "exec"), namespace)  # noqa: S102
        raw: Dict[str, Any] = namespace.get("LOCATOR_REGISTRY", {})
        result: Dict[str, Dict[str, Any]] = {}
        for key, meta in raw.items():
            result[key] = {
                "suggested_key": key,
                "description": meta.get("description", ""),
                "locators": meta.get("locators", []),
                "confidence": 1.0,  # 已审核，视为满分
            }
        return result
    except Exception as e:
        print(f"[warn] 解析现有 registry 失败，将覆盖重建: {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="从 JSONL outputs 构建 Locator Registry")
    p.add_argument(
        "--outputs",
        default="outputs",
        help="csv_runner 输出目录（默认 outputs/）",
    )
    p.add_argument(
        "--registry",
        default="../../test_reading_framework/locators/locator_registry.py",
        help="目标 locator_registry.py 路径",
    )
    p.add_argument(
        "--min-confidence",
        type=float,
        default=0.6,
        help="最低 confidence 阈值（默认 0.6）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印预览，不写文件",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    outputs_dir = Path(args.outputs)
    registry_path = Path(args.registry)

    if not outputs_dir.exists():
        print(f"[error] outputs 目录不存在: {outputs_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"[info] 扫描 {outputs_dir} ...")
    candidates = collect_candidates(outputs_dir, args.min_confidence)
    print(f"[info] 提取到 {len(candidates)} 个去重候选（confidence >= {args.min_confidence}）")

    if not candidates:
        print("[info] 无候选，退出。")
        return

    added, skipped = merge_into_registry(registry_path, candidates, args.dry_run)
    print(f"[summary] 新增={added}  跳过={skipped}")


if __name__ == "__main__":
    main()
