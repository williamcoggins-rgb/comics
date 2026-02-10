# unified_comics_rules_engine_studio.py
"""
Unified Comics Writing Rules Engine + Studio Mode (Idea Generation)

Modes:
- Critic Mode (default): evaluate an input spec JSON.
- Studio Mode (--generate): generate N rule-aligned comic idea specs from a seed.

Auto-fix modes (no story rewrites):
  --apply-fixes none|safe|suggest
    safe   = structural placeholders & tags only
    suggest= safe + generate 5–6 options for hooks/stakes/balloon splits (not applied)

Studio Mode:
  --generate --n 5 --seed '{"genre":"noir sci-fi","tone":"tense","page_count":22,"hook":"memory theft"}'
Outputs JSON with generated_specs[] each including spec + summary + gate + results.

Design:
- Generation is template-based + constrained to satisfy your rule set by construction.
- No LLM required; you can later swap generators with model calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum, IntEnum
from typing import Any, Callable, Dict, List, Optional, Tuple
import argparse
import json
import math
import random
import re
import sys


# ---------------------------------------------------------------------
# PRIORITY (higher number = higher priority)
# ---------------------------------------------------------------------


class Priority(IntEnum):
    P0_HARD_CONSTRAINTS = 100
    P1_STORY_FUNCTION = 80
    P2_COMICS_SPECIFICITY = 60
    P3_DRAMA_AND_PACING = 40
    P4_TRANSITIONS = 30
    P5_STRUCTURE_SHAPE = 20
    P6_MEDIUM_CONSTRAINTS = 10
    P7_REWRITE_LOOP = 0


class Level(IntEnum):
    PASS = 0
    NOTE = 1
    WARN = 2
    FAIL = 3


@dataclass
class RuleResult:
    ok: bool
    rule_id: str
    priority: Priority
    level: Level
    message: str
    location: Optional[str] = None
    fixes: List[str] = field(default_factory=list)
    fix_functions: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Rule:
    rule_id: str
    priority: Priority
    description: str
    check: Callable[[Dict[str, Any]], List[RuleResult]]


def make_result(
    *,
    rule_id: str,
    priority: Priority,
    level: Level,
    message: str,
    location: Optional[str] = None,
    fixes: Optional[List[str]] = None,
    fix_functions: Optional[List[str]] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> RuleResult:
    return RuleResult(
        ok=(level != Level.FAIL),
        rule_id=rule_id,
        priority=priority,
        level=level,
        message=message,
        location=location,
        fixes=list(fixes or []),
        fix_functions=list(fix_functions or []),
        evidence=dict(evidence or {}),
    )


class RulesEngine:
    def __init__(self) -> None:
        self.rules: List[Rule] = []

    def register(self, rule: Rule) -> None:
        self.rules.append(rule)
        self.rules.sort(key=lambda r: int(r.priority), reverse=True)

    def evaluate(
        self,
        spec: Dict[str, Any],
        *,
        stop_on_first_failing_priority: bool = True,
        stop_threshold: Priority = Priority.P0_HARD_CONSTRAINTS,
    ) -> List[RuleResult]:
        results: List[RuleResult] = []
        current_bucket: Optional[Priority] = None
        bucket_failed = False

        for rule in self.rules:
            if current_bucket is None:
                current_bucket = rule.priority
            elif rule.priority != current_bucket:
                if stop_on_first_failing_priority and bucket_failed and current_bucket >= stop_threshold:
                    break
                current_bucket = rule.priority
                bucket_failed = False

            try:
                res = rule.check(spec)
                if isinstance(res, list):
                    results.extend(res)
                    if any(r.level == Level.FAIL for r in res):
                        bucket_failed = True
                else:
                    results.append(
                        make_result(
                            rule_id=f"{rule.rule_id}.BAD_RETURN",
                            priority=rule.priority,
                            level=Level.FAIL,
                            message="Rule returned non-list; expected list[RuleResult].",
                            evidence={"returned_type": str(type(res))},
                        )
                    )
                    bucket_failed = True
            except Exception as e:
                results.append(
                    make_result(
                        rule_id=f"{rule.rule_id}.EXCEPTION",
                        priority=rule.priority,
                        level=Level.FAIL,
                        message=f"Rule crashed: {e}",
                        fixes=["Fix the spec shape for this rule or harden the rule against missing fields."],
                        evidence={"exception": repr(e)},
                    )
                )
                bucket_failed = True

        results.sort(key=lambda rr: (-int(rr.level), -int(rr.priority)))
        return results


# ---------------------------------------------------------------------
# Shared helpers / indexing
# ---------------------------------------------------------------------

_WORD_RE = re.compile(r"\b[\w'']+\b", flags=re.UNICODE)


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def safe_list(x: Any) -> List[Any]:
    return x if isinstance(x, list) else []


def get_medium_target(spec: Dict[str, Any]) -> str:
    return (spec.get("medium_target") or "comics").strip().lower()


def get_pages(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    return safe_list(spec.get("pages"))


class SpecIndex:
    def __init__(self, spec: Dict[str, Any]) -> None:
        self.spec = spec
        self.pages: List[Dict[str, Any]] = get_pages(spec)
        self.page_no_to_index: Dict[int, int] = {}
        for idx, p in enumerate(self.pages):
            page_no = p.get("page_no")
            if isinstance(page_no, int) and page_no not in self.page_no_to_index:
                self.page_no_to_index[page_no] = idx

    def ensure_scenes(self) -> List[Dict[str, Any]]:
        scenes = self.spec.get("scenes")
        if isinstance(scenes, list):
            if scenes:
                return scenes
            return scenes

        inferred: List[Dict[str, Any]] = []
        for idx, p in enumerate(self.pages):
            page_no = p.get("page_no", idx + 1)
            inferred.append(
                {
                    "scene_id": f"PAGE_{page_no}",
                    "purpose": "",
                    "entry_hook": "",
                    "exit_hook": "",
                    "next_scene_id": None,
                    "page_no": page_no,
                }
            )
        self.spec["scenes"] = inferred
        return inferred

    def scenes(self) -> List[Dict[str, Any]]:
        scenes = self.spec.get("scenes")
        if isinstance(scenes, list):
            return scenes
        return self.ensure_scenes()


def get_scenes(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    return SpecIndex(spec).scenes()


def panel_text_entries(panel: Dict[str, Any]) -> List[Dict[str, str]]:
    txt = panel.get("text", [])
    if isinstance(txt, list) and txt and isinstance(txt[0], dict):
        return [t for t in txt if isinstance(t, dict)]
    if isinstance(txt, list) and txt and isinstance(txt[0], str):
        return [{"type": "balloon", "value": s} for s in txt if isinstance(s, str)]
    return []


def estimate_panel_seconds(panel: Dict[str, Any]) -> float:
    base = 1.2
    entries = panel_text_entries(panel)
    total_words = sum(word_count(e.get("value", "")) for e in entries)
    read_seconds = total_words / 3.0
    balloon_count = len(entries)
    switching = max(0, balloon_count - 2) * 0.35
    if total_words == 0:
        if (panel.get("silent_intent") or "").strip():
            return base + 0.8
        return base
    return base + read_seconds + switching


def split_sentences(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    return re.split(r"(?<=[\.\!\?…])\s+", text)


def truncate_words(text: str, n: int) -> str:
    words = _WORD_RE.findall(text or "")
    if len(words) <= n:
        return text.strip()
    return " ".join(words[:n]).rstrip() + "…"


def parse_balloon_ptr(ptr: str) -> Tuple[str, int, int, int]:
    m = re.match(r"pi(\d+)-pn(\d+)-b(\d+)$", ptr)
    if m:
        return ("pi", int(m.group(1)) - 1, int(m.group(2)) - 1, int(m.group(3)) - 1)
    m = re.match(r"p(\d+)-pn(\d+)-b(\d+)$", ptr)
    if m:
        return ("pno", int(m.group(1)), int(m.group(2)) - 1, int(m.group(3)) - 1)
    return ("bad", -1, -1, -1)


# ---------------------------------------------------------------------
# Fix functions (mutators)
# ---------------------------------------------------------------------


class FixCapability(str, Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"


FixFn = Callable[..., None]


def fix_add_entry_hook(spec: Dict[str, Any], scene_id: str, hook: str) -> None:
    idx = SpecIndex(spec)
    for s in idx.ensure_scenes():
        if s.get("scene_id") == scene_id:
            s["entry_hook"] = hook
            return


def fix_add_exit_hook(spec: Dict[str, Any], scene_id: str, hook: str) -> None:
    idx = SpecIndex(spec)
    for s in idx.ensure_scenes():
        if s.get("scene_id") == scene_id:
            s["exit_hook"] = hook
            return


def fix_overlap_dialogue_transition(spec: Dict[str, Any], from_scene: str, to_scene: str, bridging_line: str) -> None:
    fix_add_exit_hook(spec, from_scene, bridging_line)
    fix_add_entry_hook(spec, to_scene, bridging_line)


def fix_reduce_balloon_load(panel: Dict[str, Any], target_total_words: int = 35) -> None:
    entries = panel_text_entries(panel)
    joined = " ".join(e.get("value", "") for e in entries)
    words = _WORD_RE.findall(joined)
    if len(words) > target_total_words:
        joined = " ".join(words[:target_total_words]).rstrip() + "…"
    panel["text"] = [{"type": "balloon", "value": joined}]


def fix_add_scene_outcome(spec: Dict[str, Any], scene_id: str, outcome: str) -> None:
    idx = SpecIndex(spec)
    for s in idx.ensure_scenes():
        if s.get("scene_id") == scene_id:
            s["outcome"] = outcome
            return


def fix_tag_page_turn(spec: Dict[str, Any], page_no: int, label: str = "") -> None:
    for p in get_pages(spec):
        if p.get("page_no") == page_no:
            p["page_turn_reveal"] = True
            if label:
                p["reveal_label"] = label
            return


def fix_set_central_conflict(spec: Dict[str, Any], conflict: str, conflict_type: str = "") -> None:
    spec["central_conflict"] = conflict
    if conflict_type:
        spec["central_conflict_type"] = conflict_type


def fix_add_character_role(spec: Dict[str, Any], role: str, name: str) -> None:
    chars = safe_list(spec.get("characters"))
    for c in chars:
        if (c.get("role") or "").lower() == role.lower():
            c["name"] = name
            spec["characters"] = chars
            return
    chars.append({"role": role, "name": name})
    spec["characters"] = chars


def fix_set_protagonist_need(spec: Dict[str, Any], need: str) -> None:
    spec["protagonist_need"] = need


FIX_REGISTRY: Dict[str, Tuple[FixCapability, FixFn]] = {
    "fix_add_entry_hook": (FixCapability.SAFE, fix_add_entry_hook),
    "fix_add_exit_hook": (FixCapability.SAFE, fix_add_exit_hook),
    "fix_add_scene_outcome": (FixCapability.SAFE, fix_add_scene_outcome),
    "fix_tag_page_turn": (FixCapability.SAFE, fix_tag_page_turn),
    "fix_set_central_conflict": (FixCapability.SAFE, fix_set_central_conflict),
    "fix_add_character_role": (FixCapability.SAFE, fix_add_character_role),
    "fix_set_protagonist_need": (FixCapability.SAFE, fix_set_protagonist_need),
    "fix_overlap_dialogue_transition": (FixCapability.SAFE, fix_overlap_dialogue_transition),
    "fix_reduce_balloon_load": (FixCapability.UNSAFE, fix_reduce_balloon_load),
}

SAFE_FIX_FUNCS = {name for name, (cap, _) in FIX_REGISTRY.items() if cap == FixCapability.SAFE}


# ---------------------------------------------------------------------
# SUGGESTION GENERATORS
# ---------------------------------------------------------------------


def suggest_entry_hook_options(spec: Dict[str, Any], scene: Dict[str, Any]) -> List[str]:
    who = (spec.get("protagonist") or "Protagonist")
    goal = (spec.get("protagonist_goal") or "a clear goal")
    prem = (spec.get("premise") or "").strip()
    purpose = (scene.get("purpose") or "purpose beat").lower()
    return [
        f"[Where/When] — {who} steps into change: a new {purpose}.",
        f"After the break: {who} chases {goal}, but something's off.",
        f"Meanwhile, {who} finds the cost of {goal} just went up.",
        f"[Location card] — the moment *after* the status quo cracks.",
        f"A simple task turns sharp: {who} is forced to choose.",
        f"Orientation: we're here because {prem or 'the situation shifted'}.",
    ]


def suggest_exit_hook_options(spec: Dict[str, Any], scene: Dict[str, Any]) -> List[str]:
    who = (spec.get("protagonist") or "Protagonist")
    stakes = (spec.get("stakes") or "the cost rises")
    nxt = (scene.get("next_scene_id") or "next scene")
    return [
        f"A threat lands—move or lose: {stakes}.",
        f"{who} decides, knowing the price isn't paid yet.",
        "A question with teeth: what happens if they're wrong?",
        f"The door opens on trouble; {nxt} can't be avoided.",
        "The clock starts; now every beat hurts.",
        "A reveal flips the board; the only way out is through.",
    ]


def suggest_balloon_options(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    sents = split_sentences(text)
    words = _WORD_RE.findall(text)
    mid = max(6, min(len(words) - 6, math.floor(len(words) / 2))) if len(words) > 12 else max(1, len(words) // 2)
    o1 = f"BALLOON 1: {truncate_words(text, mid)} | BALLOON 2: {truncate_words(' '.join(words[mid:]), 18)}"
    if len(sents) >= 2:
        o2 = f"BALLOON 1: {sents[0]} | BALLOON 2: {' '.join(sents[1:])}"
    else:
        o2 = f"BALLOON 1: {truncate_words(text, 14)} | BALLOON 2: {truncate_words(' '.join(words[14:]), 16)}"
    o3 = f"BALLOON: {truncate_words(text, 14)} | CAPTION: {truncate_words(' '.join(words[14:]), 18)}"
    o4 = f"BALLOON 1: {truncate_words(text, 12)} | BALLOON 2: {truncate_words(' '.join(words[12:]), 12)}"
    o5 = f"BALLOON 1: {truncate_words(text, 8)} | BALLOON 2: {truncate_words(' '.join(words[8:]), 10)}"
    o6 = f"BALLOON: {truncate_words(text, 10)} | NOTE: move remaining info to earlier/later beat."
    return [o1, o2, o3, o4, o5, o6]


def suggest_stakes_options(spec: Dict[str, Any]) -> List[str]:
    goal = (spec.get("protagonist_goal") or "the goal")
    stakes = (spec.get("stakes") or "").strip()
    who = (spec.get("protagonist") or "The protagonist")
    base = [
        f"If {who.lower()} fails to {goal}, someone gets hurt—name who & how.",
        f"If {goal} fails, **freedom** is lost (spell out jail/job/blacklist).",
        f"If {goal} fails, **reputation** burns (what doors close?).",
        f"If {goal} fails, **relationship** snaps (who walks?).",
        f"If {goal} fails, **time** runs out (what deadline?).",
        f"If {goal} fails, **identity** crumbles (what belief dies?).",
    ]
    if stakes:
        base.insert(0, f"Refine: \u201cIf {who} fails to {goal}, then {stakes}.\u201d Make the loss concrete.")
    return base


def ensure_suggestions_bucket(spec: Dict[str, Any]) -> Dict[str, Any]:
    if "suggestions" not in spec or not isinstance(spec["suggestions"], dict):
        spec["suggestions"] = {}
    return spec["suggestions"]


# ---------------------------------------------------------------------
# RULES
# ---------------------------------------------------------------------


def rule_spec_schema_shape(spec: Dict[str, Any]) -> List[RuleResult]:
    problems: List[str] = []
    if not isinstance(spec, dict):
        return [
            make_result(
                rule_id="P0.SPEC_SCHEMA_SHAPE",
                priority=Priority.P0_HARD_CONSTRAINTS,
                level=Level.FAIL,
                message="Spec must be a JSON object (dict).",
                evidence={"received_type": str(type(spec))},
            )
        ]

    pages = spec.get("pages")
    if pages is None:
        problems.append("Missing required key: pages (list).")
    elif not isinstance(pages, list):
        problems.append(f"pages must be a list; got {type(pages)}.")
    else:
        for pi, page in enumerate(pages, start=1):
            if not isinstance(page, dict):
                problems.append(f"pages[{pi}] must be an object; got {type(page)}.")
                continue
            page_no = page.get("page_no")
            if page_no is not None and not isinstance(page_no, int):
                problems.append(f"pages[{pi}].page_no must be int; got {type(page_no)}.")
            panels = page.get("panels")
            if panels is None:
                problems.append(f"pages[{pi}] missing panels (list).")
                continue
            if not isinstance(panels, list):
                problems.append(f"pages[{pi}].panels must be a list; got {type(panels)}.")
                continue
            for pj, panel in enumerate(panels, start=1):
                if not isinstance(panel, dict):
                    problems.append(f"pages[{pi}].panels[{pj}] must be an object; got {type(panel)}.")
                    continue
                has_any_content = bool((panel.get("art") or "").strip()) or bool(safe_list(panel.get("beats"))) or bool(safe_list(panel.get("text"))) or bool(safe_list(panel.get("dialogue")))
                if not has_any_content:
                    problems.append(f"pages[{pi}].panels[{pj}] has no content (art/beats/text/dialogue).")

    if problems:
        return [
            make_result(
                rule_id="P0.SPEC_SCHEMA_SHAPE",
                priority=Priority.P0_HARD_CONSTRAINTS,
                level=Level.FAIL,
                message="Spec schema/shape problems detected.",
                fixes=[
                    "Ensure spec is a JSON object with pages: [ {page_no:int, panels:[{art:str, text:list}]} ].",
                    "Panels must contain at least one content bucket: art OR beats OR text OR dialogue.",
                ],
                evidence={"problems": problems[:50]},
            )
        ]
    return [
        make_result(
            rule_id="P0.SPEC_SCHEMA_SHAPE",
            priority=Priority.P0_HARD_CONSTRAINTS,
            level=Level.PASS,
            message="Spec schema shape looks sane.",
        )
    ]


def rule_script_min_fields(spec: Dict[str, Any]) -> List[RuleResult]:
    pages = get_pages(spec)
    if not pages:
        return [
            make_result(
                rule_id="P0.SCRIPT_MIN_FIELDS",
                priority=Priority.P0_HARD_CONSTRAINTS,
                level=Level.FAIL,
                message="Script missing pages.",
                fixes=["Provide pages: [{page_no, page_type, panels:[{art, text:[...]}]}]."],
            )
        ]
    problems: List[str] = []
    for i, page in enumerate(pages, start=1):
        panels = safe_list(page.get("panels"))
        if not panels:
            problems.append(f"Page {page.get('page_no', i)}: no panels.")
            continue
        for j, panel in enumerate(panels, start=1):
            if not (panel.get("art") or "").strip():
                problems.append(f"Page {page.get('page_no', i)}, Panel {j}: missing art direction.")
            txt = panel.get("text", [])
            if txt is not None and not isinstance(txt, list):
                problems.append(f"Page {page.get('page_no', i)}, Panel {j}: text must be a list.")
    if problems:
        return [
            make_result(
                rule_id="P0.SCRIPT_MIN_FIELDS",
                priority=Priority.P0_HARD_CONSTRAINTS,
                level=Level.FAIL,
                message="Script minimum field problems detected.",
                fixes=[
                    "Add art direction to every panel (what the artist must draw).",
                    "Store dialogue/captions/sfx as a list so lettering is deterministic.",
                ],
                evidence={"problems": problems[:80]},
            )
        ]
    return [make_result(rule_id="P0.SCRIPT_MIN_FIELDS", priority=Priority.P0_HARD_CONSTRAINTS, level=Level.PASS, message="Script minimum fields pass.")]


def rule_hybrid_language(spec: Dict[str, Any]) -> List[RuleResult]:
    pages = get_pages(spec)
    if not pages:
        return [make_result(rule_id="P0.HYBRID_LANGUAGE", priority=Priority.P0_HARD_CONSTRAINTS, level=Level.FAIL, message="No pages provided.", fixes=["Provide pages with panels."])]
    fails: List[str] = []
    for i, page in enumerate(pages, start=1):
        for j, panel in enumerate(safe_list(page.get("panels")), start=1):
            art = (panel.get("art") or "").strip()
            entries = panel_text_entries(panel)
            has_text = len(entries) > 0
            silent_intent = (panel.get("silent_intent") or "").strip()
            if not art and has_text:
                fails.append(f"Page {page.get('page_no', i)}, Panel {j}: has text but no art instruction.")
            if art and (not has_text) and (not silent_intent):
                fails.append(f"Page {page.get('page_no', i)}, Panel {j}: has art but no text and no silent_intent.")
    if fails:
        return [
            make_result(
                rule_id="P0.HYBRID_LANGUAGE",
                priority=Priority.P0_HARD_CONSTRAINTS,
                level=Level.FAIL,
                message="Word/image integration failures detected.",
                fixes=["Add silent_intent for art-only panels; add art direction for text-only panels."],
                evidence={"failures": fails[:80]},
            )
        ]
    return [make_result(rule_id="P0.HYBRID_LANGUAGE", priority=Priority.P0_HARD_CONSTRAINTS, level=Level.PASS, message="Word/image integration passes.")]


def rule_page_panel_sanity(spec: Dict[str, Any]) -> List[RuleResult]:
    pages = get_pages(spec)
    if not pages:
        return [make_result(rule_id="P0.PAGE_SANITY", priority=Priority.P0_HARD_CONSTRAINTS, level=Level.FAIL, message="No pages provided.")]
    problems: List[str] = []
    for i, page in enumerate(pages, start=1):
        panels = safe_list(page.get("panels"))
        page_type = (page.get("page_type") or "normal").strip().lower()
        count = len(panels)
        if page_type in {"splash", "full_page_shot"} and count > 3:
            problems.append(f"Page {page.get('page_no', i)}: {page_type} too many panels ({count}).")
        if page_type == "normal" and count == 0:
            problems.append(f"Page {page.get('page_no', i)}: normal page has zero panels.")
        if count > 9:
            problems.append(f"Page {page.get('page_no', i)}: too many panels ({count}).")
    if problems:
        return [make_result(rule_id="P0.PAGE_SANITY", priority=Priority.P0_HARD_CONSTRAINTS, level=Level.FAIL, message="Page structure problems detected.", evidence={"problems": problems[:80]})]
    return [make_result(rule_id="P0.PAGE_SANITY", priority=Priority.P0_HARD_CONSTRAINTS, level=Level.PASS, message="Page structure passes.")]


def rule_story_definition(spec: Dict[str, Any]) -> List[RuleResult]:
    premise = (spec.get("premise") or "").strip()
    protagonist = (spec.get("protagonist") or "").strip()
    change = (spec.get("character_change") or "").strip()
    proposition = (spec.get("proposition") or "").strip()
    target_emotion = (spec.get("target_emotion") or "").strip()
    missing = []
    if not premise:
        missing.append("premise")
    if not protagonist:
        missing.append("protagonist")
    if not (change or proposition or target_emotion):
        missing.append("one of: character_change | proposition | target_emotion")
    if missing:
        return [make_result(rule_id="P1.STORY_DEFINITION", priority=Priority.P1_STORY_FUNCTION, level=Level.FAIL, message=f"Missing: {', '.join(missing)}.")]
    return [make_result(rule_id="P1.STORY_DEFINITION", priority=Priority.P1_STORY_FUNCTION, level=Level.PASS, message="Story definition satisfied.")]


def rule_structure_has_consequences(spec: Dict[str, Any]) -> List[RuleResult]:
    beats = safe_list(spec.get("beats"))
    if len(beats) < 4:
        return [make_result(rule_id="P1.STORY_STRUCTURE_MIN", priority=Priority.P1_STORY_FUNCTION, level=Level.FAIL, message="Need at least 4 beats.")]
    hollow = [b for b in beats if not (b.get("change") or b.get("new_problem") or b.get("cost"))]
    if hollow:
        return [make_result(rule_id="P1.STORY_STRUCTURE_CONSEQUENCE", priority=Priority.P1_STORY_FUNCTION, level=Level.FAIL, message="Some beats lack change/cost/new_problem.", evidence={"hollow_beats_count": len(hollow)})]
    return [make_result(rule_id="P1.STORY_STRUCTURE_CONSEQUENCE", priority=Priority.P1_STORY_FUNCTION, level=Level.PASS, message="Beats carry consequences.")]


def rule_creating_drama(spec: Dict[str, Any]) -> List[RuleResult]:
    goal = (spec.get("protagonist_goal") or "").strip()
    obstacles = safe_list(spec.get("obstacles"))
    stakes = (spec.get("stakes") or "").strip()
    missing = []
    if not goal:
        missing.append("protagonist_goal")
    if len(obstacles) < 2:
        missing.append(">=2 obstacles")
    if not stakes:
        missing.append("stakes")
    if missing:
        return [make_result(rule_id="P2.CREATING_DRAMA", priority=Priority.P2_COMICS_SPECIFICITY, level=Level.FAIL, message=f"Missing: {', '.join(missing)}.")]
    return [make_result(rule_id="P2.CREATING_DRAMA", priority=Priority.P2_COMICS_SPECIFICITY, level=Level.PASS, message="Drama fundamentals present.")]


def rule_characterization_choice(spec: Dict[str, Any]) -> List[RuleResult]:
    moments = safe_list(spec.get("character_reveals"))
    if len(moments) < 1:
        return [make_result(rule_id="P2.CHARACTERIZATION_CHOICE", priority=Priority.P2_COMICS_SPECIFICITY, level=Level.FAIL, message="Need >=1 character reveal moment.")]
    weak = [m for m in moments if not (m.get("pressure") and m.get("choice") and m.get("cost"))]
    if weak:
        return [make_result(rule_id="P2.CHARACTERIZATION_CHOICE", priority=Priority.P2_COMICS_SPECIFICITY, level=Level.FAIL, message="Some reveals missing pressure/choice/cost.", evidence={"weak_reveals": len(weak)})]
    return [make_result(rule_id="P2.CHARACTERIZATION_CHOICE", priority=Priority.P2_COMICS_SPECIFICITY, level=Level.PASS, message="Character reveals are choice-driven.")]


def rule_sloane_absorption_hooks(spec: Dict[str, Any]) -> List[RuleResult]:
    idx = SpecIndex(spec)
    scenes = idx.scenes()
    if not scenes:
        return [make_result(rule_id="SLOANE.SCENES_RECOMMENDED", priority=Priority.P6_MEDIUM_CONSTRAINTS, level=Level.NOTE, message="No scenes found.")]
    results: List[RuleResult] = []
    for s in scenes:
        sid = s.get("scene_id") or "UNKNOWN"
        if not (s.get("purpose") or "").strip():
            results.append(make_result(rule_id="SLOANE.PURPOSE_REQUIRED", priority=Priority.P1_STORY_FUNCTION, level=Level.FAIL, message="Scene purpose missing.", location=f"scene:{sid}"))
        if not (s.get("entry_hook") or "").strip():
            results.append(make_result(rule_id="SLOANE.ENTRY_HOOK", priority=Priority.P4_TRANSITIONS, level=Level.WARN, message="Entry hook missing.", location=f"scene:{sid}", fix_functions=["fix_add_entry_hook"]))
        if not (s.get("exit_hook") or "").strip():
            results.append(make_result(rule_id="SLOANE.EXIT_PROPULSION", priority=Priority.P4_TRANSITIONS, level=Level.WARN, message="Exit hook missing.", location=f"scene:{sid}", fix_functions=["fix_add_exit_hook"]))
    return results or [make_result(rule_id="SLOANE.ABSORPTION_HOOKS", priority=Priority.P4_TRANSITIONS, level=Level.PASS, message="Scene hooks ok.")]


def rule_scene_outcome_direction(spec: Dict[str, Any]) -> List[RuleResult]:
    scenes = get_scenes(spec)
    missing = [s.get("scene_id") for s in scenes if not (s.get("outcome") or "").strip()]
    if missing:
        return [make_result(rule_id="SCENE.OUTCOME_DIRECTION", priority=Priority.P4_TRANSITIONS, level=Level.WARN, message="Scene outcomes missing.", evidence={"scenes": missing[:50]}, fix_functions=["fix_add_scene_outcome"])]
    return [make_result(rule_id="SCENE.OUTCOME_DIRECTION", priority=Priority.P4_TRANSITIONS, level=Level.PASS, message="Scene outcomes present.")]


def rule_comics_grid_page_turns(spec: Dict[str, Any]) -> List[RuleResult]:
    pages = get_pages(spec)
    if len(pages) < 3:
        return []
    flagged = [p for p in pages if p.get("page_turn_reveal")]
    if not flagged:
        return [make_result(rule_id="GRID.PAGE_TURN_REVEALS", priority=Priority.P4_TRANSITIONS, level=Level.WARN, message="No page-turn reveal tagged.", fix_functions=["fix_tag_page_turn"])]
    return [make_result(rule_id="GRID.PAGE_TURN_REVEALS", priority=Priority.P4_TRANSITIONS, level=Level.PASS, message="Page-turn reveal tagged.")]


def rule_conflict_four_levels(spec: Dict[str, Any]) -> List[RuleResult]:
    scenes = get_scenes(spec)
    obstacles = safe_list(spec.get("obstacles"))
    internal_ok = bool((spec.get("character_change") or spec.get("internal_conflict") or spec.get("target_emotion")))
    central_ok = bool((spec.get("central_conflict") or spec.get("central_conflict_type")))
    micro_ok = all(bool(s.get("conflict")) for s in scenes) if scenes else False
    macro_ok = len(obstacles) >= 2
    missing = []
    if not central_ok:
        missing.append("central conflict")
    if not macro_ok:
        missing.append("macro obstacles")
    if not micro_ok:
        missing.append("micro conflicts")
    if not internal_ok:
        missing.append("internal conflict")
    if missing:
        return [make_result(rule_id="CONFLICT.FOUR_LEVELS", priority=Priority.P2_COMICS_SPECIFICITY, level=Level.WARN, message="Conflict coverage incomplete.", evidence={"missing": missing}, fix_functions=["fix_set_central_conflict"])]
    return [make_result(rule_id="CONFLICT.FOUR_LEVELS", priority=Priority.P2_COMICS_SPECIFICITY, level=Level.PASS, message="Conflict coverage ok.")]


def rule_dcosta_inciting_incident_timing(spec: Dict[str, Any]) -> List[RuleResult]:
    beats = safe_list(spec.get("beats"))
    inciting_indexes = []
    for idx, b in enumerate(beats):
        name = (b.get("name") or "").lower()
        if b.get("new_problem") or ("inciting" in name) or ("disturbance" in name):
            inciting_indexes.append(idx)
    if not any(i <= 1 for i in inciting_indexes):
        return [make_result(rule_id="DCOSTA.INCITING_TIMING", priority=Priority.P1_STORY_FUNCTION, level=Level.FAIL, message="Inciting incident not clearly early.", evidence={"inciting_indexes": inciting_indexes})]
    return [make_result(rule_id="DCOSTA.INCITING_TIMING", priority=Priority.P1_STORY_FUNCTION, level=Level.PASS, message="Inciting incident early enough.")]


_STAKE_KEYWORDS = {"life", "death", "freedom", "jail", "reputation", "family", "job", "mission", "city", "world", "identity", "time", "deadline"}


def rule_dcosta_stakes_specificity(spec: Dict[str, Any]) -> List[RuleResult]:
    s = (spec.get("stakes") or "").strip()
    wc = word_count(s)
    hits = {w for w in _STAKE_KEYWORDS if re.search(rf"\b{re.escape(w)}\b", s.lower())}
    if wc < 8 or len(hits) == 0:
        level = Level.FAIL if wc < 8 else Level.WARN
        return [make_result(rule_id="DCOSTA.STAKES_SPECIFICITY", priority=Priority.P2_COMICS_SPECIFICITY, level=level, message="Stakes too vague.", evidence={"word_count": wc, "keyword_hits": sorted(hits)})]
    return [make_result(rule_id="DCOSTA.STAKES_SPECIFICITY", priority=Priority.P2_COMICS_SPECIFICITY, level=Level.PASS, message="Stakes specific enough.")]


def rule_myers_family_roles(spec: Dict[str, Any]) -> List[RuleResult]:
    chars = safe_list(spec.get("characters"))
    roles_present = {(c.get("role") or "").lower() for c in chars}
    coverage = len(roles_present.intersection({"protagonist", "nemesis", "mentor", "attractor", "trickster"}))
    if coverage < 3:
        return [make_result(rule_id="MYERS.FAMILY_ROLES", priority=Priority.P1_STORY_FUNCTION, level=Level.WARN, message="Too few family roles.", evidence={"roles_present": sorted(roles_present)}, fix_functions=["fix_add_character_role"])]
    return [make_result(rule_id="MYERS.FAMILY_ROLES", priority=Priority.P1_STORY_FUNCTION, level=Level.PASS, message="Family roles ok.")]


def rule_myers_unity_arc(spec: Dict[str, Any]) -> List[RuleResult]:
    need = (spec.get("protagonist_need") or spec.get("internal_conflict") or "").strip()
    if not need:
        return [make_result(rule_id="MYERS.UNITY_ARC", priority=Priority.P1_STORY_FUNCTION, level=Level.WARN, message="No protagonist_need / unity arc.", fix_functions=["fix_set_protagonist_need"])]
    return [make_result(rule_id="MYERS.UNITY_ARC", priority=Priority.P1_STORY_FUNCTION, level=Level.PASS, message="Unity arc hint present.")]


# PRIEST PACK

_FAKE_DIALECT_RE = re.compile(r"\b(ah|muh|mah)\b", flags=re.IGNORECASE)


def rule_priest_dialogue_cleanliness(spec: Dict[str, Any]) -> List[RuleResult]:
    pages = get_pages(spec)
    violations: List[str] = []
    for i, page in enumerate(pages, 1):
        for j, panel in enumerate(safe_list(page.get("panels")), 1):
            for e in panel_text_entries(panel):
                val = (e.get("value") or "")
                if _FAKE_DIALECT_RE.search(val):
                    violations.append(f"page:{page.get('page_no', i)} panel:{j} -> {val}")
    if violations:
        return [RuleResult(False, "PRIEST.DIALOGUE_CLEANLINESS", Priority.P0_HARD_CONSTRAINTS, Level.FAIL,
            "Fake dialect crutches detected (rewrite using rhythm/syntax, not misspelling).",
            fixes=["Rewrite dialect without phonetic spelling crutches (keep it readable)."],
            evidence={"violations": violations[:40]})]
    return [RuleResult(True, "PRIEST.DIALOGUE_CLEANLINESS", Priority.P0_HARD_CONSTRAINTS, Level.PASS, "Dialogue cleanliness OK.")]


def rule_priest_copy_heavy(spec: Dict[str, Any]) -> List[RuleResult]:
    pages = get_pages(spec)
    heavy: List[str] = []
    for i, page in enumerate(pages, 1):
        for j, panel in enumerate(safe_list(page.get("panels")), 1):
            sec = estimate_panel_seconds(panel)
            if sec > 12.0:
                heavy.append(f"page:{page.get('page_no', i)} panel:{j} ({round(sec,2)}s)")
    if heavy:
        return [RuleResult(True, "PRIEST.COPY_HEAVY", Priority.P0_HARD_CONSTRAINTS, Level.WARN,
            "Copy-heavy panels detected (risk: reader stall).",
            fixes=["Split the panel or trim balloons; move info into visuals."],
            fix_functions=["fix_reduce_balloon_load"],
            evidence={"panels": heavy[:30]})]
    return [RuleResult(True, "PRIEST.COPY_HEAVY", Priority.P0_HARD_CONSTRAINTS, Level.PASS, "Copy density acceptable.")]


def rule_priest_layout_tricks(spec: Dict[str, Any]) -> List[RuleResult]:
    pages = get_pages(spec)
    bad_pages: List[Any] = []
    for i, page in enumerate(pages, 1):
        if (page.get("layout") or "").strip().lower() in {"trick", "gimmick", "pretentious"}:
            bad_pages.append(page.get("page_no", i))
    if bad_pages:
        return [RuleResult(True, "PRIEST.LAYOUT_TRICKS", Priority.P0_HARD_CONSTRAINTS, Level.WARN,
            "Trick/gimmick layouts flagged (risk: readability).",
            fixes=["Prefer clear left-to-right, top-to-bottom panel flow unless the trick is story-critical."],
            evidence={"pages": bad_pages})]
    return [RuleResult(True, "PRIEST.LAYOUT_TRICKS", Priority.P0_HARD_CONSTRAINTS, Level.PASS, "Layouts clean.")]


def rule_priest_interior_splash(spec: Dict[str, Any]) -> List[RuleResult]:
    pages = get_pages(spec)
    if len(pages) < 3:
        return []
    interior = []
    for idx, page in enumerate(pages, 1):
        pt = (page.get("page_type") or "normal").strip().lower()
        if pt == "splash" and idx not in {1, len(pages)}:
            interior.append(page.get("page_no", idx))
    if interior:
        return [RuleResult(True, "PRIEST.INTERIOR_SPLASH", Priority.P2_COMICS_SPECIFICITY, Level.WARN,
            "Interior splash pages flagged (use sparingly; ensure purpose is undeniable).",
            fixes=["Confirm the splash delivers a major turn/reveal; otherwise convert to a strong normal page."],
            evidence={"pages": interior})]
    return [RuleResult(True, "PRIEST.INTERIOR_SPLASH", Priority.P2_COMICS_SPECIFICITY, Level.PASS, "Splash placement OK.")]


def rule_priest_mindless_violence(spec: Dict[str, Any]) -> List[RuleResult]:
    beats = safe_list(spec.get("beats"))
    flagged = []
    for b in beats:
        text = (b.get("name", "") + " " + b.get("change", "") + " " + b.get("new_problem", "")).lower()
        if any(k in text for k in ["fight", "punch", "shoot", "kill", "battle", "attack"]):
            if not (b.get("cost") or b.get("change") or b.get("new_problem")):
                flagged.append(b)
    if flagged:
        return [RuleResult(False, "PRIEST.MINDLESS_VIOLENCE", Priority.P1_STORY_FUNCTION, Level.FAIL,
            "Violence appears without narrative consequence.",
            fixes=["Every violent act must change power, cost something, or force a new problem."],
            evidence={"beats": flagged[:10]})]
    return [RuleResult(True, "PRIEST.MINDLESS_VIOLENCE", Priority.P1_STORY_FUNCTION, Level.PASS, "Violence has consequence (or none detected).")]


def rule_priest_world_representation(spec: Dict[str, Any]) -> List[RuleResult]:
    rep = (spec.get("representation_notes") or "").strip()
    if not rep:
        return [RuleResult(True, "PRIEST.REPRESENTATION_NOTES", Priority.P1_STORY_FUNCTION, Level.NOTE,
            "Add representation_notes to avoid a default, flattened world.",
            fixes=["Add representation_notes describing who exists in this world and why (culture/class/gender/ability/etc.)."])]
    return [RuleResult(True, "PRIEST.REPRESENTATION_NOTES", Priority.P1_STORY_FUNCTION, Level.PASS, "Representation notes present.")]


# STAN LEE PACK

def rule_stan_onboarding_clarity(spec: Dict[str, Any]) -> List[RuleResult]:
    premise = (spec.get("premise") or "").strip()
    stakes = (spec.get("stakes") or "").strip()
    if len(premise.split()) < 10 or not stakes:
        return [RuleResult(True, "STAN.ONBOARDING_CLARITY", Priority.P1_STORY_FUNCTION, Level.WARN,
            "Onboarding clarity is thin (premise/stakes may not orient a new reader).",
            fixes=["Expand premise: who wants what, why now, and what happens if they fail."])]
    return [RuleResult(True, "STAN.ONBOARDING_CLARITY", Priority.P1_STORY_FUNCTION, Level.PASS, "Onboarding clarity OK.")]


def rule_stan_conflict_per_scene(spec: Dict[str, Any]) -> List[RuleResult]:
    scenes = get_scenes(spec)
    if not scenes:
        return []
    missing = []
    for s in scenes:
        sid = s.get("scene_id") or "UNKNOWN"
        conflict = (s.get("conflict") or "").strip()
        if not conflict:
            missing.append(sid)
    if missing:
        return [RuleResult(True, "STAN.CONFLICT_PER_SCENE", Priority.P1_STORY_FUNCTION, Level.WARN,
            "Some scenes lack explicit conflict/opposition.",
            fixes=["Add scene.conflict (who/what resists the goal, or what dilemma exists)."],
            evidence={"scenes": missing})]
    return [RuleResult(True, "STAN.CONFLICT_PER_SCENE", Priority.P1_STORY_FUNCTION, Level.PASS, "Conflict present per scene.")]


def rule_stan_character_driven_beats(spec: Dict[str, Any]) -> List[RuleResult]:
    beats = safe_list(spec.get("beats"))
    if not beats:
        return []
    weak = [b for b in beats if not (b.get("character") or b.get("decision") or b.get("want"))]
    if weak:
        return [RuleResult(True, "STAN.CHARACTER_DRIVEN_BEATS", Priority.P1_STORY_FUNCTION, Level.WARN,
            "Some beats are not explicitly tied to a character want/decision.",
            fixes=["For each beat, add character + decision/want so events are character-driven."],
            evidence={"count": len(weak)})]
    return [RuleResult(True, "STAN.CHARACTER_DRIVEN_BEATS", Priority.P1_STORY_FUNCTION, Level.PASS, "Beats are character-driven.")]


# MOORE PACK

def rule_moore_panel_time_stoppers(spec: Dict[str, Any]) -> List[RuleResult]:
    pages = get_pages(spec)
    if not pages:
        return []
    stoppers = []
    for i, page in enumerate(pages, 1):
        for j, panel in enumerate(safe_list(page.get("panels")), 1):
            sec = estimate_panel_seconds(panel)
            if sec > 10.0 and not (panel.get("contemplative") is True):
                stoppers.append({"page": page.get("page_no", i), "panel": j, "seconds": round(sec, 2)})
    if stoppers:
        return [RuleResult(True, "MOORE.PANEL_TIME_STOPPERS", Priority.P3_DRAMA_AND_PACING, Level.WARN,
            "Overlong panels detected (likely pacing stoppers).",
            fixes=["Split into micro-actions or trim balloon load; move explanation into visuals."],
            fix_functions=["fix_reduce_balloon_load"],
            evidence={"stoppers": stoppers[:25]})]
    return [RuleResult(True, "MOORE.PANEL_TIME_STOPPERS", Priority.P3_DRAMA_AND_PACING, Level.PASS, "No obvious panel-time stoppers.")]


def rule_moore_transition_glue(spec: Dict[str, Any]) -> List[RuleResult]:
    scenes = get_scenes(spec)
    if not scenes:
        return []
    by_id = {s.get("scene_id"): s for s in scenes if s.get("scene_id")}
    missing = []
    for s in scenes:
        sid = s.get("scene_id")
        nxt_id = s.get("next_scene_id")
        if not sid or not nxt_id:
            continue
        nxt = by_id.get(nxt_id)
        if not nxt:
            continue
        if not (s.get("exit_hook") or "").strip() and not (nxt.get("entry_hook") or "").strip():
            missing.append(f"{sid}->{nxt_id}")
    if missing:
        return [RuleResult(False, "MOORE.TRANSITION_GLUE", Priority.P4_TRANSITIONS, Level.FAIL,
            "Some scene transitions lack glue (no exit_hook + no entry_hook).",
            fixes=["Use overlap dialogue (last line of Scene A lands in Scene B).", "Bridge with a shared object/image or repeated phrase."],
            fix_functions=["fix_overlap_dialogue_transition"],
            evidence={"transitions": missing[:30]})]
    return [RuleResult(True, "MOORE.TRANSITION_GLUE", Priority.P4_TRANSITIONS, Level.PASS, "Transitions have glue.")]


# MEDIUM CONSTRAINTS

def rule_medium_constraints(spec: Dict[str, Any]) -> List[RuleResult]:
    target = get_medium_target(spec)
    results: List[RuleResult] = []
    results.append(RuleResult(True, "COMICS.ALLOTTED_READING_TIME", Priority.P6_MEDIUM_CONSTRAINTS, Level.NOTE,
        "Assume each panel has an allotted reading time; match balloon load to intended rhythm.",
        fixes=["Audit action pages: keep panels visually clear and balloon-light to preserve speed."]))
    if target == "film_adaptation":
        results.extend([
            RuleResult(True, "ADAPT.LAYOUT_TRANSLATION", Priority.P6_MEDIUM_CONSTRAINTS, Level.WARN,
                "Film adaptation risk: page-turn reveals and page layout rhythm must be re-authored for a single screen.",
                fixes=["List every page-turn reveal and design its film equivalent (cut/reveal movement/focus)."]),
            RuleResult(True, "ADAPT.SILENCE_TO_SOUND", Priority.P6_MEDIUM_CONSTRAINTS, Level.WARN,
                "Film adaptation risk: comics silence is pacing; film sound can over-explain.",
                fixes=["Tag silent beats that must remain silent (no score/no dialogue)."]),
        ])
    return results


def rule_rewrite_loop(spec: Dict[str, Any]) -> List[RuleResult]:
    return [RuleResult(True, "PROCESS.REWRITE_LOOP", Priority.P7_REWRITE_LOOP, Level.NOTE,
        "Plan at least one rewrite pass focused ONLY on reader absorption and clarity.",
        fixes=["Do a pass where every panel earns its keep: remove or compress anything that doesn't change the situation."])]


# ---------------------------------------------------------------------
# BUILD ENGINE
# ---------------------------------------------------------------------


def build_unified_comics_engine() -> RulesEngine:
    eng = RulesEngine()

    eng.register(Rule("P0.SPEC_SCHEMA_SHAPE", Priority.P0_HARD_CONSTRAINTS, "Schema sanity (stop-the-line).", rule_spec_schema_shape))
    eng.register(Rule("P0.SCRIPT_MIN_FIELDS", Priority.P0_HARD_CONSTRAINTS, "Drawable/letterable.", rule_script_min_fields))
    eng.register(Rule("P0.HYBRID_LANGUAGE", Priority.P0_HARD_CONSTRAINTS, "Words + pictures integrated.", rule_hybrid_language))
    eng.register(Rule("P0.PAGE_SANITY", Priority.P0_HARD_CONSTRAINTS, "Readable pages.", rule_page_panel_sanity))
    eng.register(Rule("PRIEST.DIALOGUE_CLEANLINESS", Priority.P0_HARD_CONSTRAINTS, "No fake dialect crutches.", rule_priest_dialogue_cleanliness))
    eng.register(Rule("PRIEST.COPY_HEAVY", Priority.P0_HARD_CONSTRAINTS, "Avoid copy-heavy panels.", rule_priest_copy_heavy))
    eng.register(Rule("PRIEST.LAYOUT_TRICKS", Priority.P0_HARD_CONSTRAINTS, "Avoid trick layouts.", rule_priest_layout_tricks))

    eng.register(Rule("P1.STORY_DEFINITION", Priority.P1_STORY_FUNCTION, "Premise + protagonist + change/proposition/emotion.", rule_story_definition))
    eng.register(Rule("P1.STORY_STRUCTURE_CONSEQUENCE", Priority.P1_STORY_FUNCTION, "Beats carry consequence.", rule_structure_has_consequences))
    eng.register(Rule("DCOSTA.INCITING_TIMING", Priority.P1_STORY_FUNCTION, "Inciting lands early.", rule_dcosta_inciting_incident_timing))
    eng.register(Rule("MYERS.FAMILY_ROLES", Priority.P1_STORY_FUNCTION, "Character role coverage.", rule_myers_family_roles))
    eng.register(Rule("MYERS.UNITY_ARC", Priority.P1_STORY_FUNCTION, "Psych need stated.", rule_myers_unity_arc))
    eng.register(Rule("PRIEST.MINDLESS_VIOLENCE", Priority.P1_STORY_FUNCTION, "Violence must have consequence.", rule_priest_mindless_violence))
    eng.register(Rule("PRIEST.REPRESENTATION_NOTES", Priority.P1_STORY_FUNCTION, "Representation notes required (advisory).", rule_priest_world_representation))
    eng.register(Rule("STAN.ONBOARDING_CLARITY", Priority.P1_STORY_FUNCTION, "Every issue must orient a new reader.", rule_stan_onboarding_clarity))
    eng.register(Rule("STAN.CONFLICT_PER_SCENE", Priority.P1_STORY_FUNCTION, "Conflict per scene.", rule_stan_conflict_per_scene))
    eng.register(Rule("STAN.CHARACTER_DRIVEN_BEATS", Priority.P1_STORY_FUNCTION, "Beats tied to character decision/want.", rule_stan_character_driven_beats))

    eng.register(Rule("P2.CREATING_DRAMA", Priority.P2_COMICS_SPECIFICITY, "Goal/obstacles/stakes present.", rule_creating_drama))
    eng.register(Rule("P2.CHARACTERIZATION_CHOICE", Priority.P2_COMICS_SPECIFICITY, "Pressure/choice/cost.", rule_characterization_choice))
    eng.register(Rule("DCOSTA.STAKES_SPECIFICITY", Priority.P2_COMICS_SPECIFICITY, "Stakes concrete.", rule_dcosta_stakes_specificity))
    eng.register(Rule("CONFLICT.FOUR_LEVELS", Priority.P2_COMICS_SPECIFICITY, "Conflict coverage.", rule_conflict_four_levels))
    eng.register(Rule("PRIEST.INTERIOR_SPLASH", Priority.P2_COMICS_SPECIFICITY, "Flag interior splash pages.", rule_priest_interior_splash))

    eng.register(Rule("MOORE.PANEL_TIME_STOPPERS", Priority.P3_DRAMA_AND_PACING, "Flag overlong panels.", rule_moore_panel_time_stoppers))

    eng.register(Rule("SLOANE.ABSORPTION_HOOKS", Priority.P4_TRANSITIONS, "Scene purpose + hooks.", rule_sloane_absorption_hooks))
    eng.register(Rule("SCENE.OUTCOME_DIRECTION", Priority.P4_TRANSITIONS, "Scene outcomes.", rule_scene_outcome_direction))
    eng.register(Rule("MOORE.TRANSITION_GLUE", Priority.P4_TRANSITIONS, "Ensure transition glue.", rule_moore_transition_glue))
    eng.register(Rule("GRID.PAGE_TURN_REVEALS", Priority.P4_TRANSITIONS, "Page-turn reveals.", rule_comics_grid_page_turns))

    eng.register(Rule("MEDIUM.CONSTRAINTS", Priority.P6_MEDIUM_CONSTRAINTS, "Medium constraints reminders.", rule_medium_constraints))
    eng.register(Rule("PROCESS.REWRITE_LOOP", Priority.P7_REWRITE_LOOP, "Rewrite pass reminder.", rule_rewrite_loop))

    return eng


# ---------------------------------------------------------------------
# AUTO-FIX & SUGGESTIONS
# ---------------------------------------------------------------------


def apply_safe_autofixes(spec: Dict[str, Any], results: List[RuleResult]) -> None:
    idx = SpecIndex(spec)
    idx.ensure_scenes()

    for r in results:
        if r.rule_id in {"SLOANE.ENTRY_HOOK"} and r.location and r.location.startswith("scene:"):
            sid = r.location.split("scene:")[-1]
            fix_add_entry_hook(spec, sid, f"[TODO entry hook for {sid}]")
        if r.rule_id in {"SLOANE.EXIT_PROPULSION"} and r.location and r.location.startswith("scene:"):
            sid = r.location.split("scene:")[-1]
            fix_add_exit_hook(spec, sid, f"[TODO exit hook for {sid}]")

    for r in results:
        if r.rule_id == "SCENE.OUTCOME_DIRECTION":
            for sid in r.evidence.get("scenes", []):
                if sid:
                    fix_add_scene_outcome(spec, sid, f"[TODO outcome for {sid}]")

    if any(r.rule_id == "GRID.PAGE_TURN_REVEALS" and r.level == Level.WARN for r in results):
        pages = get_pages(spec)
        if pages:
            mid_idx = max(0, (len(pages) // 2) - 1)
            page_no = pages[mid_idx].get("page_no", mid_idx + 1)
            if isinstance(page_no, int):
                fix_tag_page_turn(spec, page_no, "auto-suggested")

    for r in results:
        if r.rule_id == "CONFLICT.FOUR_LEVELS":
            missing = " ".join(r.evidence.get("missing", []))
            if "central conflict" in missing and not spec.get("central_conflict"):
                fix_set_central_conflict(spec, "[TBD central conflict]", "")

    if any(r.rule_id == "MYERS.FAMILY_ROLES" and r.level == Level.WARN for r in results):
        for role in ["protagonist", "nemesis", "mentor"]:
            fix_add_character_role(spec, role, f"[TBD {role}]")

    if any(r.rule_id == "MYERS.UNITY_ARC" and r.level == Level.WARN for r in results):
        if not spec.get("protagonist_need"):
            fix_set_protagonist_need(spec, "[TBD psychological need]")


def collect_suggestions(spec: Dict[str, Any], results: List[RuleResult]) -> Dict[str, List[str]]:
    suggestions = ensure_suggestions_bucket(spec)
    idx = SpecIndex(spec)
    scenes = idx.scenes()
    scene_by_id = {s.get("scene_id"): s for s in scenes if s.get("scene_id")}

    for r in results:
        if r.rule_id == "SLOANE.ENTRY_HOOK" and r.location and r.location.startswith("scene:"):
            sid = r.location.split("scene:")[-1]
            suggestions[f"scene:{sid}:entry_hook"] = suggest_entry_hook_options(spec, scene_by_id.get(sid, {}))
        if r.rule_id == "SLOANE.EXIT_PROPULSION" and r.location and r.location.startswith("scene:"):
            sid = r.location.split("scene:")[-1]
            suggestions[f"scene:{sid}:exit_hook"] = suggest_exit_hook_options(spec, scene_by_id.get(sid, {}))

    if any(r.rule_id in {"DCOSTA.STAKES_SPECIFICITY", "P2.CREATING_DRAMA"} for r in results):
        suggestions["stakes:options"] = suggest_stakes_options(spec)

    return suggestions


# ---------------------------------------------------------------------
# Summary / gate
# ---------------------------------------------------------------------


def _summarize(results: List[RuleResult]) -> Dict[str, Any]:
    counts = {"FAIL": 0, "WARN": 0, "NOTE": 0, "PASS": 0}
    by_priority: Dict[str, Dict[str, int]] = {}
    for r in results:
        lvl = r.level.name
        counts[lvl] += 1
        by_priority.setdefault(r.priority.name, {"FAIL": 0, "WARN": 0, "NOTE": 0, "PASS": 0})
        by_priority[r.priority.name][lvl] += 1
    status = "green"
    if counts["FAIL"] > 0:
        status = "red"
    elif counts["WARN"] > 0:
        status = "yellow"
    return {"status": status, "counts": counts, "by_priority": by_priority}


def _priority_from_str(name: str) -> Priority:
    name = name.strip().upper()
    mapping = {
        "P0": Priority.P0_HARD_CONSTRAINTS,
        "P1": Priority.P1_STORY_FUNCTION,
        "P2": Priority.P2_COMICS_SPECIFICITY,
        "P3": Priority.P3_DRAMA_AND_PACING,
        "P4": Priority.P4_TRANSITIONS,
        "P5": Priority.P5_STRUCTURE_SHAPE,
        "P6": Priority.P6_MEDIUM_CONSTRAINTS,
        "P7": Priority.P7_REWRITE_LOOP,
    }
    if name in mapping:
        return mapping[name]
    try:
        return Priority[name]
    except KeyError as e:
        raise ValueError(f"Unknown priority '{name}'. Use P0..P7 or enum name.") from e


def gate_results(results: List[RuleResult], min_priority: Priority) -> Tuple[bool, Optional[str]]:
    failures = [r for r in results if r.level == Level.FAIL and r.priority >= min_priority]
    if not failures:
        return True, None
    lines = []
    for f in failures:
        loc = f" @ {f.location}" if f.location else ""
        lines.append(f"[{f.priority.name}] {f.rule_id}{loc}: {f.message}")
    return False, "RulesEngine gate failed:\n" + "\n".join(lines)


# ---------------------------------------------------------------------
# STUDIO MODE (Idea generation)
# ---------------------------------------------------------------------


def _seed_get(seed: Dict[str, Any], key: str, default: Any) -> Any:
    v = seed.get(key, default)
    return default if v is None else v


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "idea"


def _pick(rng: random.Random, xs: List[str]) -> str:
    return xs[rng.randrange(0, len(xs))]


def _unique_obstacles(rng: random.Random, pool: List[str], n: int) -> List[str]:
    pool = list(dict.fromkeys(pool))
    rng.shuffle(pool)
    return pool[: max(2, min(n, len(pool)))]


def build_idea_spec(seed: Dict[str, Any], idea_index: int, rng: random.Random) -> Dict[str, Any]:
    genre = str(_seed_get(seed, "genre", "superhero thriller")).strip()
    tone = str(_seed_get(seed, "tone", "tense, propulsive")).strip()
    page_count = int(_seed_get(seed, "page_count", 22))
    hook = str(_seed_get(seed, "hook", "a stolen secret")).strip()
    setting = str(_seed_get(seed, "setting", "a city where lies demonstrate truth")).strip()

    prot_names = ["Mara", "Kade", "Inez", "Sol", "Juno", "Rafi", "Nyx", "Orion", "Vale", "Sable"]
    nem_names = ["Vesper", "Crown", "Gallows", "Silk", "Archon", "Morrow", "Heliot", "Cinder", "Kestrel", "Proxy"]
    mentor_names = ["Dr. Quill", "Aunt Sera", "Captain Roe", "Brother Ash", "Ms. Rook", "Old Finch", "Agent Lark"]
    jobs = ["courier", "public defender", "street medic", "systems auditor", "museum guard", "tabloid reporter", "union organizer"]
    flaws = ["control issues", "avoidance", "ruthless pragmatism", "fear of intimacy", "pride", "impulsiveness", "self-erasure"]
    needs = [
        "learn to trust help",
        "accept accountability without self-destruction",
        "choose mercy without losing strength",
        "stop confusing control with safety",
        "tell the truth even when it costs love",
        "protect others without martyring the self",
    ]
    goals = [
        "deliver proof before it disappears",
        "stop a public execution staged as justice",
        "recover a stolen memory map",
        "expose the architect behind the coups",
        "save a hostage exchange from collapse",
        "prevent a ritual that rewrites identities",
    ]
    stakes_templates = [
        "If they fail to {goal}, freedom is lost and the city spirals into sanctioned violence under a deadline.",
        "If they fail to {goal}, a family member is erased from public records and time runs out before dawn.",
        "If they fail to {goal}, reputation is destroyed, a mission collapses, and prison becomes inevitable.",
        "If they fail to {goal}, identity is rewritten and the community fractures into factions within hours.",
    ]
    obstacle_pool = [
        "a legal trap that makes the truth inadmissible",
        "a rival who benefits from chaos",
        "a mentor's secret compromise",
        "a resource deadline (power, blood, money, oxygen)",
        "a crowd that turns into a weapon",
        "an internal relapse into the old flaw",
        "an ally who lies to protect you",
        "a surveillance net that punishes movement",
        "a fake peace offer designed to stall you",
        "a second villain with a different agenda",
    ]

    protagonist = _pick(rng, prot_names)
    nemesis = _pick(rng, nem_names)
    mentor = _pick(rng, mentor_names)
    job = _pick(rng, jobs)
    flaw = _pick(rng, flaws)
    need = _pick(rng, needs)
    goal = _pick(rng, goals)

    premise = (
        f"In {setting}, a {job} named {protagonist} runs into {hook} and must {goal}, "
        f"but {nemesis} weaponizes the system to force {protagonist} back into their worst habit."
    )
    target_emotion = f"{tone} with escalating dread and a clean cathartic release."
    protagonist_goal = goal
    protagonist_motivation = f"Protect someone vulnerable and prove they can be more than {flaw}."
    stakes = _pick(rng, stakes_templates).format(goal=protagonist_goal)

    central_conflict = f"{protagonist} vs {nemesis}: control of the truth that decides who is punished and who is protected."
    internal_conflict = f"{protagonist} believes control prevents loss; the story forces them to {need}."
    character_change = f"{protagonist} shifts from {flaw} toward {need} under escalating cost."

    obstacles = _unique_obstacles(rng, obstacle_pool, n=3)

    character_reveals = [
        {
            "pressure": f"{nemesis} offers a shortcut that rewards {flaw}.",
            "choice": f"take the shortcut or accept a slower, riskier path that requires {need}",
            "cost": "lose time and protection; risk someone's safety",
        }
    ]

    subplot_budget = 1 if page_count <= 22 else 2
    subplots = [{"name": "An ally's loyalty test", "purpose": "forces a moral cost"}][:subplot_budget]

    beats = [
        {"name": "Inciting Disturbance", "new_problem": f"{hook} lands in {protagonist}'s hands and {nemesis} notices.", "change": "The status quo breaks in public.", "cost": "A deadline starts and allies become liabilities.", "character": protagonist},
        {"name": "Complication", "new_problem": f"A trap makes {protagonist_goal} illegal or impossible by normal means.", "change": "The world's rules clamp down.", "cost": "A relationship fractures and resources shrink.", "character": protagonist},
        {"name": "Escalation", "new_problem": f"{nemesis} flips an ally and turns the crowd into a weapon.", "change": "The plan becomes a chase with visible consequences.", "cost": "A public loss damages reputation and freedom.", "character": nemesis},
        {"name": "Payoff / Knockout", "new_problem": "Final confrontation at the worst possible moment.", "change": f"{protagonist} chooses {need} instead of {flaw}, winning at a personal cost.", "cost": "A scar remains; the victory changes future choices.", "character": protagonist},
    ]

    min_pages = max(3, min(6, page_count))
    pages: List[Dict[str, Any]] = []
    for pno in range(1, min_pages + 1):
        panels: List[Dict[str, Any]] = []
        for pn in range(1, 5):
            art = f"{genre} tone. {setting}. Beat hint: {beats[min(3, pno - 1)]['name']}."
            panel: Dict[str, Any] = {"art": art}
            if pno == 1 and pn == 1:
                panel["text"] = [{"type": "caption", "value": f"{protagonist} \u2014 {job}. {setting}."}]
            elif pn == 4:
                panel["text"] = [{"type": "caption", "value": f"Pressure rises: {obstacles[min(len(obstacles)-1, pno-1)]}."}]
            else:
                panel["silent_intent"] = f"Visual beat: {protagonist} advances toward {protagonist_goal} with new cost."
                panel["text"] = []
            panels.append(panel)
        pages.append({"page_no": pno, "page_type": "normal", "panels": panels})

    mid_page_no = pages[max(0, (len(pages) // 2) - 1)]["page_no"]
    pages[mid_page_no - 1]["page_turn_reveal"] = True
    pages[mid_page_no - 1]["reveal_label"] = "The hidden truth changes the plan."

    scenes: List[Dict[str, Any]] = []
    for i, p in enumerate(pages):
        sid = f"S{i+1}"
        nxt = f"S{i+2}" if i + 1 < len(pages) else None
        purpose = ["Disturbance", "Escalation", "Reversal", "Decision", "Cost", "Payoff"][min(i, 5)]
        scenes.append({
            "scene_id": sid, "purpose": purpose,
            "entry_hook": f"{setting}. A change hits: {hook}.",
            "exit_hook": f"Propulsion: {protagonist} commits to {protagonist_goal} as {obstacles[min(len(obstacles)-1, i)]} tightens.",
            "next_scene_id": nxt,
            "conflict": f"{protagonist} vs {nemesis} through {obstacles[min(len(obstacles)-1, i)]}.",
            "outcome": f"Value shift: OPTIONS NARROW; COST UP; TRUST SHIFT on page {p['page_no']}.",
            "page_no": p["page_no"],
        })

    characters = [
        {"role": "protagonist", "name": protagonist},
        {"role": "nemesis", "name": nemesis},
        {"role": "mentor", "name": mentor},
        {"role": "attractor", "name": "An ally who tempts the flaw"},
    ]

    spec: Dict[str, Any] = {
        "title": f"{_slug(genre)}-{idea_index+1}: {protagonist} vs {nemesis}",
        "medium_target": "comics",
        "genre": genre, "tone": tone, "page_count": page_count,
        "setting": setting, "hook": hook, "premise": premise,
        "protagonist": protagonist, "protagonist_goal": protagonist_goal,
        "protagonist_motivation": protagonist_motivation, "stakes": stakes,
        "central_conflict": central_conflict,
        "central_conflict_type": seed.get("central_conflict_type", ""),
        "internal_conflict": internal_conflict, "character_change": character_change,
        "target_emotion": target_emotion, "protagonist_need": need,
        "flaws": [flaw],
        "backstory": f"{protagonist} learned that {flaw} feels like safety after a past loss tied to {setting}.",
        "obstacles": obstacles, "subplots": subplots, "beats": beats,
        "character_reveals": character_reveals, "characters": characters,
        "scenes": scenes, "pages": pages,
    }
    return spec


def generate_specs(
    engine: RulesEngine, seed: Dict[str, Any], n: int,
    gate_min_priority: Priority, max_attempts: int,
    apply_fixes_mode: str, include_results: bool,
) -> List[Dict[str, Any]]:
    rng_seed = _seed_get(seed, "rng_seed", 1337)
    rng = random.Random(int(rng_seed))
    out: List[Dict[str, Any]] = []

    for idea_i in range(n):
        best_payload: Optional[Dict[str, Any]] = None
        best_score = -10_000

        for attempt in range(max_attempts):
            spec = build_idea_spec(seed, idea_index=idea_i * max_attempts + attempt, rng=rng)
            results = engine.evaluate(spec, stop_on_first_failing_priority=True)

            if apply_fixes_mode in {"safe", "suggest"}:
                apply_safe_autofixes(spec, results)
                if apply_fixes_mode == "suggest":
                    collect_suggestions(spec, results)
                results = engine.evaluate(spec, stop_on_first_failing_priority=True)

            summary = _summarize(results)
            ok, gate_message = gate_results(results, gate_min_priority)

            score = 0
            for r in results:
                if r.level == Level.FAIL:
                    score -= 300 + int(r.priority)
                elif r.level == Level.WARN:
                    score -= 20 + (int(r.priority) // 10)
                elif r.level == Level.NOTE:
                    score -= 2
                else:
                    score += 1

            payload: Dict[str, Any] = {
                "summary": summary,
                "gate": {"min_priority": gate_min_priority.name, "ok": ok, "message": gate_message},
                "spec": spec,
            }
            if include_results:
                payload["results"] = [asdict(r) for r in results]

            if ok:
                out.append(payload)
                break

            if score > best_score:
                best_score = score
                best_payload = payload
        else:
            out.append(best_payload or {
                "summary": {"status": "red"},
                "gate": {"min_priority": gate_min_priority.name, "ok": False, "message": "No attempts."},
                "spec": {},
            })

    return out


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def main_cli(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Unified Comics Writing Rules Engine + Studio Mode")
    ap.add_argument("--in", dest="infile", required=False, default="-", help="Input JSON spec (Critic Mode). '-' for stdin.")
    ap.add_argument("--out", dest="outfile", required=False, default="-", help="Output JSON (results). '-' for stdout.")
    ap.add_argument("--out-spec", dest="outspec", required=False, default=None, help="Write mutated spec JSON here (safe/suggest).")
    ap.add_argument("--gate", dest="gate", required=False, default="P1", help="Minimum priority gate for FAILs (P0..P7). Default P1.")
    ap.add_argument("--apply-fixes", dest="apply_fixes", choices=["none", "safe", "suggest"], default="none",
        help="none = no changes; safe = structural placeholders only; suggest = safe + idea options (not applied).")

    ap.add_argument("--generate", action="store_true", help="Studio Mode: generate idea specs instead of evaluating input.")
    ap.add_argument("--n", type=int, default=5, help="Number of idea specs to generate (Studio Mode).")
    ap.add_argument("--max-attempts", type=int, default=6, help="Max attempts per idea slot (Studio Mode).")
    ap.add_argument("--seed", type=str, default="{}", help='Seed JSON string.')
    ap.add_argument("--include-results", action="store_true", help="Include full rule results in Studio Mode output.")
    ap.add_argument("--full-report", action="store_true", help="Evaluate all priorities even if P0/P1 fails.")
    args = ap.parse_args(argv)

    engine = build_unified_comics_engine()

    try:
        min_pri = _priority_from_str(args.gate)
    except Exception as e:
        _write_json(args.outfile, {"error": f"Invalid --gate: {e}"})
        return 2

    if args.generate:
        try:
            seed = json.loads(args.seed)
            if not isinstance(seed, dict):
                raise ValueError("seed must be a JSON object")
        except Exception as e:
            _write_json(args.outfile, {"error": f"Invalid --seed JSON: {e}"})
            return 2

        generated = generate_specs(
            engine=engine, seed=seed, n=max(1, args.n),
            gate_min_priority=min_pri, max_attempts=max(1, args.max_attempts),
            apply_fixes_mode=args.apply_fixes, include_results=args.include_results,
        )
        out_payload = {
            "mode": "studio",
            "seed": seed,
            "gate": {"min_priority": min_pri.name},
            "generated_specs": generated,
            "fix_registry": {name: cap.value for name, (cap, _) in FIX_REGISTRY.items()},
        }
        _write_json(args.outfile, out_payload)
        return 0 if all(item["gate"]["ok"] for item in generated) else 2

    spec = _read_spec(args.infile)
    results = engine.evaluate(spec, stop_on_first_failing_priority=(not args.full_report))

    if args.apply_fixes in {"safe", "suggest"}:
        apply_safe_autofixes(spec, results)
        if args.apply_fixes == "suggest":
            collect_suggestions(spec, results)
        results = engine.evaluate(spec, stop_on_first_failing_priority=(not args.full_report))

    summary = _summarize(results)
    ok, gate_message = gate_results(results, min_pri)

    out_payload = {
        "mode": "critic",
        "summary": summary,
        "results": [asdict(r) for r in results],
        "gate": {"min_priority": min_pri.name, "ok": ok, "message": gate_message},
        "suggestions": spec.get("suggestions", {}) if args.apply_fixes == "suggest" else {},
        "fix_registry": {name: cap.value for name, (cap, _) in FIX_REGISTRY.items()},
    }

    _write_json(args.outfile, out_payload)

    if args.outspec:
        with open(args.outspec, "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2, ensure_ascii=False)

    return 0 if ok else 2


def _read_spec(infile: str) -> Dict[str, Any]:
    if infile == "-":
        data = json.load(sys.stdin)
    else:
        with open(infile, "r", encoding="utf-8") as f:
            data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Input spec must be a JSON object.")
    return data


def _write_json(outfile: str, payload: Dict[str, Any]) -> None:
    if outfile == "-":
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
        print()
        return
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main_cli())
