# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

"""Guided onboarding: the step graph and its engine.

The flow is a directed graph, not a wizard with a fixed page order. Each step declares its
preconditions, how to detect that it is already satisfied, and what it contributes to the
plan. The engine walks the graph, skipping satisfied steps and blocking illegal ones, so
the ordering rules the service enforces are visible in the interface instead of arriving
as errors.

Every step re-derives its state from the service, which is what makes the flow resumable,
idempotent, and usable as a repair tool.

This module is deliberately free of any UI framework import.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


class StepState(Enum):
    SATISFIED = "satisfied"
    CURRENT = "current"
    PENDING = "pending"
    BLOCKED = "blocked"

    @property
    def is_actionable(self) -> bool:
        return self in (StepState.CURRENT, StepState.PENDING)


@dataclass
class PlanItem:
    """One operation the flow will perform, shown before anything is applied."""

    key: str
    description: str
    command: str = ""
    #: exists / create / modify / blocked
    action: str = "create"
    depends_on: Tuple[str, ...] = ()
    #: Execution phase. Steps are ordered for selection, but operations must run in
    #: dependency order: grants before the links that need them, or linking fails with an
    #: authorization error that looks like a backend fault.
    phase: int = 50
    long_running: bool = True
    invoke: Optional[Callable[..., Any]] = None
    #: Optional readiness check run after the mutation poller completes.
    verify: Optional[Callable[..., Any]] = None
    target: str = ""
    category: str = "operation"
    blocked_reason: str = ""

    @property
    def is_actionable(self) -> bool:
        return self.action in ("create", "modify")


@dataclass
class Step:
    """One node of the onboarding graph."""

    id: str
    title: str
    #: Ids of steps that must be satisfied before this one is legal.
    after: Tuple[str, ...] = ()
    #: Given the flow's context, is this step already done? Must consult live state.
    detect: Optional[Callable[[Dict[str, Any]], bool]] = None
    #: Why the step is blocked, when its predecessors are unmet.
    blocked_reason: str = ""
    #: True when the step may be skipped without leaving the namespace unusable.
    optional: bool = False
    #: Steps the customer never chooses. They still contribute to the plan, but the rail
    #: lists decisions only - an automatic operation shown as a "step" reads as a chore
    #: the customer has to do something about.
    hidden: bool = False
    #: Builds the plan entries this step contributes, given the selections made.
    plan: Optional[Callable[[Dict[str, Any]], List[PlanItem]]] = None
    #: Will this step be satisfied by the plan itself, given the selections made so far?
    #: Without this, a first-time setup could never show a complete plan: every step would
    #: look blocked by the one before it, which has not run yet.
    planned: Optional[Callable[[Dict[str, Any]], bool]] = None

    def is_satisfied(self, context: Dict[str, Any]) -> bool:
        return bool(self.detect(context)) if self.detect else False

    def is_planned(self, context: Dict[str, Any]) -> bool:
        return bool(self.planned(context)) if self.planned else False

    def will_hold(self, context: Dict[str, Any]) -> bool:
        """True when this step is already done, or the plan will make it so."""
        return self.is_satisfied(context) or self.is_planned(context)


@dataclass
class Flow:
    """Walks the step graph against live state."""

    steps: List[Step]
    context: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self._by_id = {step.id: step for step in self.steps}

    # -- state -------------------------------------------------------------

    def state_of(self, step: Step) -> StepState:
        if step.is_satisfied(self.context):
            return StepState.SATISFIED
        if self.blocking(step):
            return StepState.BLOCKED
        return StepState.PENDING

    def blocking(self, step: Step) -> List[Step]:
        """Predecessors that will not hold, even after the plan runs."""
        return [
            self._by_id[dependency]
            for dependency in step.after
            if dependency in self._by_id and not self._by_id[dependency].will_hold(self.context)
        ]

    def visible_steps(self) -> List[Step]:
        """Decisions only, in order. What the rail shows."""
        return [step for step in self.steps if not step.hidden]

    def states(self) -> List[Tuple[Step, StepState]]:
        """Every visible step with its state, first actionable one marked current."""
        resolved = [(step, self.state_of(step)) for step in self.visible_steps()]
        for index, (step, state) in enumerate(resolved):
            if state is StepState.PENDING:
                resolved[index] = (step, StepState.CURRENT)
                break
        return resolved

    def current(self) -> Optional[Step]:
        for step, state in self.states():
            if state is StepState.CURRENT:
                return step
        return None

    def satisfied(self) -> List[Step]:
        return [step for step in self.steps if step.is_satisfied(self.context)]

    @property
    def is_complete(self) -> bool:
        return all(step.is_satisfied(self.context) or step.optional for step in self.steps)

    def progress(self) -> Tuple[int, int]:
        required = [
            step for step in self.visible_steps() if not step.optional
        ]
        done = [step for step in required if step.is_satisfied(self.context)]
        return len(done), len(required)

    # -- planning ----------------------------------------------------------

    def build_plan(self) -> List[PlanItem]:
        """Collect plan entries, ordered for execution rather than for selection.

        Nothing is mutated here: the plan is the contract shown to the user before apply.
        """
        items = self._collect_plan()
        # Stable sort keeps each phase in its declared order.
        return sorted(items, key=lambda item: item.phase)

    def _collect_plan(self) -> List[PlanItem]:
        items: List[PlanItem] = []
        for step in self.steps:
            state = self.state_of(step)
            if state is StepState.SATISFIED:
                items.append(
                    PlanItem(
                        key=step.id,
                        description=f"{step.title} - already configured",
                        action="exists",
                        # Context first: what is already true, before what will change.
                        phase=0,
                        long_running=False,
                    )
                )
                continue
            if state is StepState.BLOCKED:
                blockers = ", ".join(blocked.title for blocked in self.blocking(step))
                items.append(
                    PlanItem(
                        key=step.id,
                        description=step.title,
                        action="blocked",
                        blocked_reason=step.blocked_reason or f"requires: {blockers}",
                        phase=0,
                        long_running=False,
                    )
                )
                continue
            if step.plan is not None:
                items.extend(step.plan(self.context) or [])
        return items

    def script(self) -> str:
        """The plan as a runnable script: plan-only mode, and the audit trail."""
        lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
        for item in self.build_plan():
            if item.action == "exists":
                lines.append(f"# {item.description}")
            elif item.action == "blocked":
                lines.append(f"# BLOCKED {item.description}: {item.blocked_reason}")
            elif item.command:
                lines.append(f"# {item.description}")
                lines.append(item.command)
                lines.append("")
        return "\n".join(lines)
