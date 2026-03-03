#!/usr/bin/env python3
"""
CSV Runner for Open-AutoGLM (failure-only screenshots)

Purpose
- Read test cases from CSV (e.g., input_and_output/ReadingApp_测试用例.csv)
- Split into sub-steps and enforce explicit finish() per sub-step
- Execute on device via PhoneAgent (Android/HarmonyOS/iOS)
- Emit one JSON object per case into a JSONL file following the
  input_and_output/AGENT_OUTPUT_SCHEMA_SPEC.md (with minimal extensions)

Status: Skeleton (MVP wiring, safe fallbacks)
- Implemented: CLI, CSV parsing, sub-step splitting, per-substep loop,
  failure-only screenshots, minimal schema validation, resume,
  target package binding, ADB UI-text assertions (basic).
- TODO: element_snapshot/locator_candidate generation, richer filtering & variables,
  broader assertion types and iOS/HarmonyOS UI dumps.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

# Phone Agent
from phone_agent import PhoneAgent
from phone_agent.agent import AgentConfig
from phone_agent.device_factory import DeviceType, get_device_factory, set_device_type
from phone_agent.model import ModelConfig
from phone_agent.config import get_system_prompt

# -----------------------------
# CLI & Config
# -----------------------------

CSV_HEADERS = [
    "用例编号",
    "应用端",
    "模块",
    "用例标题",
    "前置条件",
    "页面进入步骤",
    "测试步骤",
    "预期结果",
    "优先级",
]

# reserved for future: more sophisticated numbering detection
SUBSTEP_SPLIT_SIMPLE = re.compile(r"\n|；|;")


@dataclass
class RunnerArgs:
    csv_path: Path
    out_path: Path
    run_dir: Path
    device_type: str
    device_id: Optional[str]
    base_url: str
    model: str
    apikey: str
    lang: str
    max_steps_per_substep: int
    filter_priority: Optional[str]
    filter_module: Optional[str]
    case_ids: Optional[List[str]]
    resume: bool
    dry_run: bool
    target_package: Optional[str]
    report_path: Optional[Path]


# -----------------------------
# Utilities
# -----------------------------

def _now_run_id() -> str:
    return datetime.now().strftime("run-%Y%m%d-%H%M%S")


def ensure_paths(out: Optional[str]) -> Tuple[Path, Path]:
    outputs = Path("outputs")
    outputs.mkdir(exist_ok=True)
    if out:
        out_path = Path(out)
        run_dir = out_path.parent if out_path.parent != Path("") else outputs
        run_dir.mkdir(parents=True, exist_ok=True)
        return out_path, run_dir
    run_id = _now_run_id()
    run_dir = outputs / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir.with_suffix(".jsonl"), run_dir


def ensure_report_path(run_dir: Path, report: Optional[str]) -> Path:
    if report:
        return Path(report)
    return run_dir / "report.csv"


def check_device_ready(args: RunnerArgs) -> None:
    set_device_type(to_device_type(args.device_type))
    df = get_device_factory()
    devices = df.list_devices()
    if not devices:
        raise RuntimeError("No devices detected. Check ADB/HDC connection.")
    print("[device] detected:")
    for d in devices:
        print(f"- {d.device_id} ({d.status})")
    if args.device_id:
        if not any(d.device_id == args.device_id for d in devices):
            raise RuntimeError(f"Device not found: {args.device_id}")
    # Basic probe
    current_app = df.get_current_app(args.device_id)
    print(f"[device] current app: {current_app}")
    shot = df.get_screenshot(args.device_id)
    print(f"[device] screenshot: {shot.width}x{shot.height}")


def read_csv_rows(csv_path: Path) -> List[Dict[str, str]]:
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows: List[Dict[str, str]] = []
        for row in reader:
            rows.append({k.strip(): (v or "").strip() for k, v in row.items() if k})
        return rows


def split_substeps(page_steps: str, test_steps: str) -> List[str]:
    merged = "\n".join([s for s in [page_steps, test_steps] if s])
    if not merged:
        return []
    parts = [p.strip() for p in SUBSTEP_SPLIT_SIMPLE.split(merged) if p and p.strip()]
    return parts


def to_device_type(dt: str) -> DeviceType:
    mapping = {"adb": DeviceType.ADB, "hdc": DeviceType.HDC, "ios": DeviceType.IOS}
    if dt not in mapping:
        raise ValueError(f"Unsupported --device-type: {dt}")
    return mapping[dt]


def b64_to_file(b64: str, path: Path) -> None:
    raw = base64.b64decode(b64)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(raw)


# -----------------------------
# Minimal schema validation (soft)
# -----------------------------

def validate_min_schema(obj: Dict[str, Any]) -> None:
    # Soft checks to avoid hard dependency on jsonschema
    if not isinstance(obj, dict):
        raise ValueError("output must be an object")
    for key in ("case_meta", "steps", "assertions", "observations"):
        if key not in obj:
            raise ValueError(f"missing required root field: {key}")
    if not isinstance(obj["steps"], list):
        raise ValueError("steps must be a list")
    if not isinstance(obj["assertions"], list):
        raise ValueError("assertions must be a list")
    if not isinstance(obj["observations"], list):
        raise ValueError("observations must be a list")


# -----------------------------
# UI tree + Assertions (ADB minimal)
# -----------------------------


def dump_ui_texts_adb(device_id: Optional[str]) -> List[str]:
    try:
        prefix = ["adb"] + (["-s", device_id] if device_id else [])
        subprocess.run(
            prefix + ["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
        )
        proc = subprocess.run(
            prefix + ["shell", "cat", "/sdcard/window_dump.xml"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
        )
        xml = proc.stdout
        if not xml:
            return []
        root = ET.fromstring(xml)
        texts: List[str] = []
        for elem in root.iter():
            t = elem.attrib.get("text")
            if t:
                texts.append(t)
            cd = elem.attrib.get("content-desc")
            if cd:
                texts.append(cd)
        return [s for s in texts if s]
    except Exception:
        return []


def dump_ui_xml_adb(device_id: Optional[str]) -> Optional[ET.Element]:
    try:
        prefix = ["adb"] + (["-s", device_id] if device_id else [])
        subprocess.run(
            prefix + ["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
        )
        proc = subprocess.run(
            prefix + ["shell", "cat", "/sdcard/window_dump.xml"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
        )
        xml = proc.stdout
        if not xml:
            return None
        return ET.fromstring(xml)
    except Exception:
        return None


def parse_bounds(bounds: str) -> Optional[Tuple[int, int, int, int]]:
    m = re.match(r"\\[(\\d+),(\\d+)\\]\\[(\\d+),(\\d+)\\]", bounds or "")
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def _build_parent_map(root: ET.Element) -> Dict[ET.Element, ET.Element | None]:
    parent: Dict[ET.Element, ET.Element | None] = {root: None}
    for p in root.iter():
        for c in list(p):
            parent[c] = p
    return parent


def _class_chain(elem: ET.Element, parent_map: Dict[ET.Element, ET.Element | None]) -> str:
    parts: List[str] = []
    cur = elem
    while cur is not None:
        cls = cur.attrib.get("class") or "UNKNOWN"
        parent = parent_map.get(cur)
        if parent is None:
            idx = 1
        else:
            siblings = [c for c in list(parent) if c.attrib.get("class") == cls]
            idx = (siblings.index(cur) + 1) if cur in siblings else 1
        parts.append(f"{cls}[{idx}]")
        cur = parent
    return "/".join(reversed(parts))


def _within(bounds: Tuple[int, int, int, int], x: int, y: int, tol: int = 0) -> bool:
    x1, y1, x2, y2 = bounds
    return (x1 - tol) <= x <= (x2 + tol) and (y1 - tol) <= y <= (y2 + tol)


def _snap(elem: ET.Element) -> Dict[str, Any]:
    return {
        "text": elem.attrib.get("text"),
        "resourceId": elem.attrib.get("resource-id"),
        "class": elem.attrib.get("class"),
        "bounds": elem.attrib.get("bounds"),
        "clickable": elem.attrib.get("clickable"),
        "contentDesc": elem.attrib.get("content-desc"),
    }


def _confidence(elem: ET.Element) -> float:
    score = 0.0
    if elem.attrib.get("resource-id"):
        score += 0.4
    if elem.attrib.get("clickable") == "true":
        score += 0.2
    if elem.attrib.get("text"):
        score += 0.2
    if elem.attrib.get("content-desc"):
        score += 0.1
    return min(1.0, score)


def _strategy_list(elem: ET.Element, parent_map: Dict[ET.Element, ET.Element | None]) -> List[Dict[str, str]]:
    strategies: List[Dict[str, str]] = []
    rid = elem.attrib.get("resource-id")
    if rid:
        strategies.append({"by": "id", "value": rid})
    cdesc = elem.attrib.get("content-desc")
    if cdesc:
        strategies.append({"by": "content_desc", "value": cdesc})
    text = elem.attrib.get("text")
    if text:
        strategies.append({"by": "text", "value": text})
    strategies.append({"by": "class_chain", "value": _class_chain(elem, parent_map)})
    return strategies


def _pick_clickable_fallback(
    elem: ET.Element, parent_map: Dict[ET.Element, ET.Element | None]
) -> ET.Element:
    has_id = bool(elem.attrib.get("resource-id"))
    has_text = bool(elem.attrib.get("text"))
    has_click = elem.attrib.get("clickable") == "true"
    has_desc = bool(elem.attrib.get("content-desc"))
    if has_id or has_text or has_desc or has_click:
        return elem
    # try clickable child
    queue = list(elem)
    while queue:
        cur = queue.pop(0)
        if cur.attrib.get("clickable") == "true":
            return cur
        queue.extend(list(cur))
    # fallback to closest clickable parent
    cur = parent_map.get(elem)
    while cur is not None:
        if cur.attrib.get("clickable") == "true":
            return cur
        cur = parent_map.get(cur)
    return elem


def build_locator_candidate_at(
    device_id: Optional[str], abs_x: int, abs_y: int
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    root = dump_ui_xml_adb(device_id)
    if root is None:
        return None, None

    parent_map = _build_parent_map(root)
    matches: List[ET.Element] = []
    for elem in root.iter():
        bounds = parse_bounds(elem.attrib.get("bounds", ""))
        if not bounds:
            continue
        if _within(bounds, abs_x, abs_y, tol=0):
            matches.append(elem)

    if not matches:
        for elem in root.iter():
            bounds = parse_bounds(elem.attrib.get("bounds", ""))
            if not bounds:
                continue
            if _within(bounds, abs_x, abs_y, tol=5):
                matches.append(elem)

    if not matches:
        return None, None

    # prefer smallest area element
    def area(e: ET.Element) -> int:
        b = parse_bounds(e.attrib.get("bounds", "")) or (0, 0, 1, 1)
        return max(1, (b[2] - b[0]) * (b[3] - b[1]))

    matches.sort(key=area)
    primary = _pick_clickable_fallback(matches[0], parent_map)

    # build strategies sorted by priority in spec
    strategies = _strategy_list(primary, parent_map)
    locator_candidate = {
        "strategies": strategies,
        "confidence": _confidence(primary),
    }
    return _snap(primary), locator_candidate


def rel_to_abs(
    rel: List[int], screen_width: int, screen_height: int
) -> Tuple[int, int]:
    x = int(rel[0] / 1000 * screen_width)
    y = int(rel[1] / 1000 * screen_height)
    return x, y




def extract_phrases(expected: str) -> List[str]:
    phrases: List[str] = []
    phrases += re.findall(r"“([^”]+)”", expected)
    phrases += re.findall(r'"([^"]+)"', expected)
    if phrases:
        return [p.strip() for p in phrases if p.strip()]
    parts = re.split(r"[，。；;,.\\n]", expected)
    return [p.strip() for p in parts if 2 <= len(p.strip()) <= 12]


def evaluate_assertions_from_expected(
    expected: str, device_type: str, device_id: Optional[str]
) -> List[Dict[str, Any]]:
    if device_type != "adb":
        return []
    ui_texts = dump_ui_texts_adb(device_id)
    phrases = extract_phrases(expected)
    assertions: List[Dict[str, Any]] = []
    for i, ph in enumerate(phrases, start=1):
        present = any(ph in t for t in ui_texts)
        assertions.append(
            {
                "assertion_index": i,
                "type_suggestion": "text_contains",
                "confidence": 0.85 if present else 0.4,
                "target": "UI_TEXT",
                "params": {"expected": ph},
                "status": "passed" if present else "failed",
            }
        )
    return assertions


# -----------------------------
# Core Runner
# -----------------------------

def build_agent(args: RunnerArgs) -> PhoneAgent:
    set_device_type(to_device_type(args.device_type))
    model_config = ModelConfig(
        base_url=args.base_url,
        model_name=args.model,
        api_key=args.apikey,
        lang=args.lang,
    )
    system_prompt = None
    if args.target_package:
        base = get_system_prompt(args.lang)
        prefix_cn = (
            f"你是移动端自动化测试Agent。本轮测试目标应用包名为 {args.target_package}。"
            "必须始终在该应用内操作，禁止切换到其他应用。"
            "每个子步骤仅完成当前目标并在结束时输出 finish(message=...)。"
        )
        prefix_en = (
            f"You are a mobile test agent. Target app package: {args.target_package}. "
            "Stay within this app; do not switch to others. "
            "For each sub-step, complete only the current goal and then output finish(message=...)."
        )
        system_prompt = (prefix_cn if args.lang == "cn" else prefix_en) + "\n\n" + base
    agent_config = AgentConfig(
        max_steps=args.max_steps_per_substep,
        device_id=args.device_id,
        lang=args.lang,
        verbose=True,
        system_prompt=system_prompt,
    )
    return PhoneAgent(model_config=model_config, agent_config=agent_config)


def run_substep(
    agent: PhoneAgent,
    substep: str,
    target_package: Optional[str] = None,
    device_type: str = "adb",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """
    Execute a single substep until the model returns finish().
    Returns: (steps, observations, raw_actions)
    steps: DSL-level step entries (without UI internals)
    observations: only on failure (screenshot_base64 carried for persistence)
    raw_actions: raw assistant action strings (for debugging)
    """
    steps: List[Dict[str, Any]] = []
    observations: List[Dict[str, Any]] = []
    raw_actions: List[str] = []

    step_index = 0
    # Strategy A: each substep in a fresh context
    agent.reset()

    while True:
        is_first = step_index == 0
        first_text = (
            substep
            if not target_package
            else (
                f"[测试上下文] 目标应用包名: {target_package}。"
                f"仅执行当前子步骤: {substep}。完成后必须输出 finish(message=...)。"
            )
        )
        res = agent.step(task=first_text) if is_first else agent.step()
        step_index += 1

        action = res.action or {}
        raw_actions.append(json.dumps(action, ensure_ascii=False))

        entry = {
            "step_index": step_index,
            "action": action.get("action") if action else None,
            "target": None,
            "zone": None,
            "params": {k: v for k, v in action.items() if k in ("text", "start", "end", "app")},
            "status": "passed" if res.success else "failed",
            "error": res.message if (not res.success and res.message) else None,
        }
        steps.append(entry)

        # Element snapshot observation (best-effort)
        if device_type == "adb" and action:
            action_name = action.get("action")
            if action_name in {"Tap", "Double Tap", "Long Press"}:
                coord = action.get("element")
                if isinstance(coord, list) and len(coord) == 2:
                    try:
                        df = get_device_factory()
                        shot = df.get_screenshot(agent.agent_config.device_id)
                        abs_x, abs_y = rel_to_abs(coord, shot.width, shot.height)
                        snap, candidate = build_locator_candidate_at(
                            agent.agent_config.device_id, abs_x, abs_y
                        )
                        if snap or candidate:
                            observations.append(
                                {
                                    "related_step": step_index,
                                    "screenshot_path": None,
                                    "element_snapshot": snap,
                                    "locator_candidate": candidate,
                                }
                            )
                    except Exception:
                        pass

        # Failure-only observation
        if not res.success:
            try:
                df = get_device_factory()
                shot = df.get_screenshot(agent.agent_config.device_id)
                observations.append(
                    {
                        "related_step": step_index,
                        "screenshot_base64": shot.base64_data,
                        "screenshot_path": None,
                        "element_snapshot": None,
                        "locator_candidate": None,
                    }
                )
            except Exception as e:
                observations.append(
                    {
                        "related_step": step_index,
                        "screenshot_base64": None,
                        "screenshot_path": None,
                        "element_snapshot": None,
                        "locator_candidate": None,
                        "error": f"screenshot failed: {e}",
                    }
                )

        if res.finished or step_index >= agent.agent_config.max_steps:
            break

    return steps, observations, raw_actions


def build_case_output(
    args: RunnerArgs,
    row: Dict[str, str],
    run_id: str,
    case_steps: List[Dict[str, Any]],
    case_assertions: List[Dict[str, Any]],
    case_observations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    case_meta = {
        "case_id": row.get("用例编号"),
        "title": row.get("用例标题"),
        "module": row.get("模块"),
        "app_side": row.get("应用端"),
        "priority": row.get("优先级"),
        "run_id": run_id,
        "timestamps": {"created": datetime.now().isoformat()},
        "device": {"type": args.device_type, "id": args.device_id},
        "target_package": args.target_package,
        "model": {"base_url": args.base_url, "name": args.model},
    }
    obj = {
        "case_meta": case_meta,
        "steps": case_steps,
        "assertions": case_assertions,
        "observations": case_observations,
    }
    return obj


def format_step_log(steps: List[Dict[str, Any]]) -> str:
    lines = []
    for s in steps:
        action = s.get("action")
        params = s.get("params") or {}
        target = s.get("target")
        status = s.get("status")
        err = s.get("error")
        parts = [f"step{int(s.get('step_index', 0))}:{action}"]
        if target:
            parts.append(f"target={target}")
        if params:
            parts.append(f"params={params}")
        parts.append(f"status={status}")
        if err:
            parts.append(f"error={err}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def derive_case_status(
    steps: List[Dict[str, Any]], assertions: List[Dict[str, Any]]
) -> Tuple[bool, str]:
    for s in steps:
        if s.get("status") == "failed":
            return False, s.get("error") or "step_failed"
    for a in assertions:
        if a.get("status") == "failed":
            expected = (a.get("params") or {}).get("expected")
            return False, f"assert_failed:{expected}" if expected else "assert_failed"
    if not steps:
        return False, "no_steps"
    return True, ""


# -----------------------------
# Main
# -----------------------------

def parse_cli() -> RunnerArgs:
    p = argparse.ArgumentParser(description="CSV→Substeps→JSONL runner (skeleton)")
    p.add_argument("--csv", dest="csv_path", required=True, help="Path to CSV file")
    p.add_argument("--out", dest="out_path", default=None, help="Output JSONL path")
    p.add_argument("--device-type", choices=["adb", "hdc", "ios"], default="adb")
    p.add_argument("--device-id", default=None)
    p.add_argument(
        "--base-url",
        default=os.getenv("PHONE_AGENT_BASE_URL", "http://localhost:8000/v1"),
    )
    p.add_argument("--model", default=os.getenv("PHONE_AGENT_MODEL", "autoglm-phone-9b"))
    p.add_argument("--apikey", default=os.getenv("PHONE_AGENT_API_KEY", "EMPTY"))
    p.add_argument("--lang", choices=["cn", "en"], default=os.getenv("PHONE_AGENT_LANG", "cn"))
    p.add_argument("--max-steps-per-substep", type=int, default=6)
    p.add_argument("--filter-priority", default=None)
    p.add_argument("--filter-module", default=None)
    p.add_argument("--case-ids", default=None, help="Comma-separated case ids to run")
    p.add_argument("--resume", action="store_true")
    p.add_argument(
        "--dry-run", action="store_true", help="Do not call model/device; still emit JSONL"
    )
    p.add_argument(
        "--target-package",
        dest="target_package",
        default=None,
        help="Target app package name (e.g., com.example.readingapp)",
    )
    p.add_argument(
        "--report",
        dest="report_path",
        default=None,
        help="Output report CSV path (default: outputs/<run>/report.csv)",
    )

    ns = p.parse_args()
    out_path, run_dir = ensure_paths(ns.out_path)

    case_ids = None
    if ns.case_ids:
        case_ids = [s.strip() for s in ns.case_ids.split(",") if s.strip()]

    return RunnerArgs(
        csv_path=Path(ns.csv_path),
        out_path=out_path,
        run_dir=run_dir,
        device_type=ns.device_type,
        device_id=ns.device_id,
        base_url=ns.base_url,
        model=ns.model,
        apikey=ns.apikey,
        lang=ns.lang,
        max_steps_per_substep=ns.max_steps_per_substep,
        filter_priority=ns.filter_priority,
        filter_module=ns.filter_module,
        case_ids=case_ids,
        resume=ns.resume,
        dry_run=ns.dry_run,
        target_package=ns.target_package,
        report_path=ensure_report_path(run_dir, ns.report_path),
    )


def load_completed_case_ids(out_path: Path) -> set[str]:
    ids: set[str] = set()
    if not out_path.exists():
        return ids
    with open(out_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                cid = obj.get("case_meta", {}).get("case_id")
                if cid:
                    ids.add(cid)
            except Exception:
                continue
    return ids


def main() -> None:
    args = parse_cli()
    rows = read_csv_rows(args.csv_path)

    def row_selected(row: Dict[str, str]) -> bool:
        if args.filter_priority and row.get("优先级") != args.filter_priority:
            return False
        if args.filter_module and row.get("模块") != args.filter_module:
            return False
        if args.case_ids and row.get("用例编号") not in args.case_ids:
            return False
        return True

    selected = [r for r in rows if row_selected(r)]

    completed_ids = load_completed_case_ids(args.out_path) if args.resume else set()

    run_id = args.run_dir.name if args.run_dir.name.startswith("run-") else _now_run_id()

    artifacts_root = args.run_dir / "artifacts"
    artifacts_root.mkdir(parents=True, exist_ok=True)

    if not args.dry_run:
        check_device_ready(args)
    agent = None if args.dry_run else build_agent(args)

    report_rows: List[Dict[str, Any]] = []

    with open(args.out_path, "a", encoding="utf-8") as out_f:
        for row in selected:
            case_id = row.get("用例编号") or "UNKNOWN"
            if args.resume and case_id in completed_ids:
                print(f"[resume] skip {case_id}")
                continue

            page_steps = row.get("页面进入步骤", "")
            test_steps = row.get("测试步骤", "")
            substeps = split_substeps(page_steps, test_steps)

            case_steps: List[Dict[str, Any]] = []
            case_observations: List[Dict[str, Any]] = []
            case_assertions: List[Dict[str, Any]] = []

            case_dir = artifacts_root / (case_id or "UNKNOWN")
            case_dir.mkdir(parents=True, exist_ok=True)

            for idx, sub in enumerate(substeps, start=1):
                print(f"[case {case_id}] substep {idx}/{len(substeps)}: {sub}")

                if args.dry_run:
                    # Note-only step in dry-run; no observation to save
                    case_steps.append(
                        {
                            "step_index": len(case_steps) + 1,
                            "action": "Note",
                            "target": None,
                            "zone": None,
                            "params": {"text": f"DRY-RUN: {sub}"},
                            "status": "passed",
                            "error": None,
                        }
                    )
                    continue

                try:
                    steps, observations, raw_actions = run_substep(
                        agent, sub, args.target_package, args.device_type
                    )

                    # Persist only failure observations (with screenshot_base64)
                    for o in observations:
                        b64 = o.pop("screenshot_base64", None)
                        if b64:
                            shot_file = case_dir / f"sub{idx:02d}_step{o['related_step']:02d}.png"
                            b64_to_file(b64, shot_file)
                            o["screenshot_path"] = str(shot_file.as_posix())
                        else:
                            o.setdefault("screenshot_path", None)

                    base = len(case_steps)
                    for s in steps:
                        s["step_index"] = base + s["step_index"]
                    case_steps.extend(steps)
                    case_observations.extend(observations)

                except Exception as e:
                    # Record failure and capture one screenshot for the substep
                    fail_index = len(case_steps) + 1
                    case_steps.append(
                        {
                            "step_index": fail_index,
                            "action": "finish",
                            "target": None,
                            "zone": None,
                            "params": {"substep": sub},
                            "status": "failed",
                            "error": str(e),
                        }
                    )
                    try:
                        if not args.dry_run:
                            df = get_device_factory()
                            shot = df.get_screenshot(agent.agent_config.device_id)
                            shot_file = case_dir / f"sub{idx:02d}_step{fail_index:02d}.png"
                            b64_to_file(shot.base64_data, shot_file)
                            case_observations.append(
                                {
                                    "related_step": fail_index,
                                    "screenshot_path": str(shot_file.as_posix()),
                                    "element_snapshot": None,
                                    "locator_candidate": None,
                                }
                            )
                    except Exception:
                        pass

            # Basic assertions from expected results using UI texts (ADB only)
            expected_text = row.get("预期结果", "") or ""
            if expected_text and not args.dry_run:
                case_assertions = evaluate_assertions_from_expected(
                    expected_text, args.device_type, args.device_id
                )

            out_obj = build_case_output(
                args=args,
                row=row,
                run_id=run_id,
                case_steps=case_steps,
                case_assertions=case_assertions,
                case_observations=case_observations,
            )
            try:
                validate_min_schema(out_obj)
            except Exception as ve:
                print(f"[warn] schema validation warning for {case_id}: {ve}")

            out_f.write(json.dumps(out_obj, ensure_ascii=False) + "\n")
            out_f.flush()
            print(f"[done] wrote case {case_id}")

            # Report row
            success, fail_reason = derive_case_status(case_steps, case_assertions)
            report_rows.append(
                {
                    "用例编号": row.get("用例编号", ""),
                    "用例标题": row.get("用例标题", ""),
                    "用例执行步骤log": format_step_log(case_steps),
                    "用例执行失败原因": "" if success else fail_reason,
                    "用例是否执行成功": "success" if success else "failed",
                }
            )

    # Write report CSV with summary success rate
    if report_rows:
        total = len(report_rows)
        ok = sum(1 for r in report_rows if r["用例是否执行成功"] == "success")
        success_rate = f"{(ok / total) * 100:.2f}%"
        report_path = args.report_path or (args.run_dir / "report.csv")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8-sig", newline="") as rf:
            writer = csv.writer(rf)
            writer.writerow(
                [
                    "用例编号",
                    "用例标题",
                    "用例执行步骤log",
                    "用例执行失败原因",
                    "用例是否执行成功",
                ]
            )
            for r in report_rows:
                writer.writerow(
                    [
                        r["用例编号"],
                        r["用例标题"],
                        r["用例执行步骤log"],
                        r["用例执行失败原因"],
                        r["用例是否执行成功"],
                    ]
                )
            writer.writerow(["", "", "", "总成功率", success_rate])
        print(f"[report] wrote {report_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
