"""落盘规划：唯一写入点、路径穿越防护、同名自动加序号。

对应 ADR-0002：免确认接收的护栏是「只写单一目录 + 绝不覆盖」。
"""
from __future__ import annotations

import os
import posixpath
from pathlib import Path


def safe_rel(rel: str) -> str:
    """校验并规范化投递内的相对路径，拒绝任何逃逸尝试。"""
    if not isinstance(rel, str) or not rel:
        raise ValueError("空的相对路径")
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or ":" in rel.split("/")[0] or "\x00" in rel:
        raise ValueError("非法的相对路径: " + rel)
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError("非法的相对路径: " + rel)
    return "/".join(parts)


def _fresh(name: str, is_dir: bool, inbox: Path) -> str:
    """同名不覆盖：报告.txt -> 报告 (2).txt；文件夹 -> 文件夹 (2)"""
    if not (inbox / name).exists():
        return name
    if is_dir:
        stem, ext = name, ""
    else:
        stem, ext = os.path.splitext(name)
    i = 2
    while True:
        candidate = f"{stem} ({i}){ext}"
        if not (inbox / candidate).exists():
            return candidate
        i += 1


def plan(inbox: Path, entries: list[dict]) -> dict[str, Path]:
    """把 header 里的 rel 映射到实际绝对路径；同一投递内共用同一套顶层重命名。"""
    rels: dict[str, str] = {}
    for e in entries:
        rel = safe_rel(e["rel"])
        rels[e["rel"]] = rel

    roots: dict[str, str] = {}
    for e in entries:
        top = rels[e["rel"]].split("/")[0]
        if top not in roots:
            roots[top] = _fresh(top, bool(e.get("dir")), inbox)

    result: dict[str, Path] = {}
    for original, rel in rels.items():
        parts = rel.split("/")
        parts[0] = roots[parts[0]]
        target = inbox.joinpath(*parts)
        # plan 之后再次确认没有跑出收件目录
        if inbox.resolve() not in target.resolve().parents:
            raise ValueError("路径逃逸被拦截: " + rel)
        result[original] = target
    return result


def ensure_parent(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
