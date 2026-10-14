"""Shared data structures: issues, scoring and the converted script model."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Weight of each construct in the success percentage.
OK = 1.0            # converted with equivalent behaviour
TRANSLATED = 0.75   # auto-translated (e.g. C -> JavaScript), needs a quick verification
PARTIAL = 0.5       # converted with an approximation, needs manual review
UNSUPPORTED = 0.0   # not converted, must be rebuilt manually

SUCCESS, PARTIAL_STATUS, FAILED = "SUCCESS", "PARTIAL", "FAILED"


def neoload_ref(name: str) -> str:
    """How a variable is referenced in NeoLoad. Single place to adapt if needed."""
    return "${" + name + "}"


@dataclass
class Issue:
    severity: str          # REVIEW (needs manual action) | INFO (note, behaviour preserved)
    file: str
    line: int
    construct: str
    message: str


@dataclass
class Tally:
    total: int = 0
    score: float = 0.0
    by_kind: Dict[str, int] = field(default_factory=dict)

    def add(self, kind: str, weight: float) -> None:
        self.total += 1
        self.score += weight
        self.by_kind[kind] = self.by_kind.get(kind, 0) + 1

    @property
    def pct(self) -> float:
        return round(100.0 * self.score / self.total, 1) if self.total else 0.0


@dataclass
class ScriptModel:
    name: str
    sections: Dict[str, list] = field(default_factory=lambda: {"init": [], "actions": [], "end": []})
    servers: Dict[Tuple[str, str, Optional[int]], str] = field(default_factory=dict)
    variables: List[dict] = field(default_factory=list)
    js_chunks: List[str] = field(default_factory=list)
    data_files: List[Tuple[str, str]] = field(default_factory=list)   # (source path, relative target)
    issues: List[Issue] = field(default_factory=list)
    tally: Tally = field(default_factory=Tally)
    stats: Dict[str, int] = field(default_factory=dict)

    def bump(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n


@dataclass
class ScriptResult:
    name: str
    source: str
    status: str
    pct: float
    constructs: int
    review_items: int
    stats: Dict[str, int]
    issues: List[Issue]
    outputs: List[str]
    error: str = ""


def decide_status(tally: Tally, issues: List[Issue], fatal: bool) -> str:
    if fatal or tally.total == 0 or tally.pct < 40.0:
        return FAILED
    if tally.score >= tally.total - 1e-9 and not any(i.severity == "REVIEW" for i in issues):
        return SUCCESS
    return PARTIAL_STATUS
