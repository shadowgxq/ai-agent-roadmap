"""W18 Session 4 dependency graph and safe parallelism rules.

Routing answers which role owns a task.  This module answers when an
assignment may start.  The graph is deliberately small and deterministic:
assignment IDs are the dependency keys, while task IDs remain the logical
aggregation keys used by the executor.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from .collaboration import CollaborationPlan, WorkerAssignment
from .decision import SplitDecisionValidationError


class DependencyGraphError(SplitDecisionValidationError):
    """Raised when assignments cannot form a valid acyclic dependency graph."""


def _ids(values: Iterable[str], field_name: str) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise DependencyGraphError(f"{field_name} 必须是字符串数组。")
    result = frozenset(values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise DependencyGraphError(f"{field_name} 只能包含非空字符串。")
    return result


@dataclass(frozen=True)
class DependencyNode:
    """A stable graph node; dependencies point to assignment IDs."""

    assignment: WorkerAssignment

    @property
    def assignment_id(self) -> str:
        return self.assignment.assignment_id

    @property
    def task_id(self) -> str:
        return self.assignment.task_id

    @property
    def dependencies(self) -> tuple[str, ...]:
        return self.assignment.dependencies


class DependencyGraph:
    """Validate and query a Manager-created assignment DAG.

    The constructor accepts either a :class:`CollaborationPlan`, an iterable
    of assignments, or a mapping keyed by assignment ID.  Input order is kept
    as the deterministic tie-breaker for ready tasks and topological sorting;
    it is never used as a substitute for dependency checks.
    """

    def __init__(
        self,
        source: CollaborationPlan | Iterable[WorkerAssignment] | Mapping[str, WorkerAssignment],
    ) -> None:
        if isinstance(source, CollaborationPlan):
            assignments = tuple(source.assignments)
        elif isinstance(source, Mapping):
            assignments = tuple(source.values())
        else:
            try:
                assignments = tuple(source)
            except TypeError as exc:
                raise DependencyGraphError(
                    "DependencyGraph source 必须是 plan、mapping 或 assignment iterable。"
                ) from exc
        if any(not isinstance(item, WorkerAssignment) for item in assignments):
            raise DependencyGraphError("DependencyGraph 只能接收 WorkerAssignment。")
        if not assignments:
            raise DependencyGraphError("DependencyGraph 至少需要一个 assignment。")

        assignment_ids = tuple(item.assignment_id for item in assignments)
        if len(assignment_ids) != len(set(assignment_ids)):
            raise DependencyGraphError("assignment_id 不能重复。")
        task_ids = tuple(item.task_id for item in assignments)
        if len(task_ids) != len(set(task_ids)):
            raise DependencyGraphError(
                "一个 DAG 中每个 task_id 只能有一个逻辑任务；重试使用同一 assignment_id。"
            )

        self._assignments = assignments
        self._nodes = {
            item.assignment_id: DependencyNode(item) for item in assignments
        }
        self._order = assignment_ids
        known = set(assignment_ids)
        self._dependencies: dict[str, tuple[str, ...]] = {}
        self._dependents: dict[str, list[str]] = {item: [] for item in assignment_ids}
        for item in assignments:
            if item.assignment_id in item.dependencies:
                raise DependencyGraphError(
                    f"assignment {item.assignment_id} 不能依赖自己。"
                )
            missing = set(item.dependencies) - known
            if missing:
                raise DependencyGraphError(
                    f"assignment {item.assignment_id} 缺少依赖：{', '.join(sorted(missing))}。"
                )
            self._dependencies[item.assignment_id] = item.dependencies
            for dependency in item.dependencies:
                self._dependents[dependency].append(item.assignment_id)
        self._topological_order = self._validate_acyclic()
        self._ancestors: dict[str, frozenset[str]] = {}
        for assignment_id in self._topological_order:
            parents = self._dependencies[assignment_id]
            self._ancestors[assignment_id] = frozenset(parents).union(
                *(self._ancestors[parent] for parent in parents)
            )

    @classmethod
    def from_plan(cls, plan: CollaborationPlan) -> "DependencyGraph":
        """Build a graph from a validated collaboration plan."""

        return cls(plan)

    @property
    def assignments(self) -> tuple[WorkerAssignment, ...]:
        return self._assignments

    @property
    def assignment_ids(self) -> tuple[str, ...]:
        return self._order

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(item.task_id for item in self._assignments)

    def __len__(self) -> int:
        return len(self._assignments)

    def __iter__(self) -> Iterator[WorkerAssignment]:
        return iter(self._assignments)

    def get(self, assignment_id: str) -> WorkerAssignment:
        try:
            return self._nodes[assignment_id].assignment
        except KeyError as exc:
            raise DependencyGraphError(
                f"不存在 assignment：{assignment_id}。"
            ) from exc

    def dependencies(self, assignment_id: str) -> tuple[str, ...]:
        self.get(assignment_id)
        return self._dependencies[assignment_id]

    def dependents(self, assignment_id: str) -> tuple[str, ...]:
        self.get(assignment_id)
        return tuple(self._dependents[assignment_id])

    def topological_order(self) -> tuple[str, ...]:
        """Return a stable topological order, not an arrival order."""

        return self._topological_order

    def ready(
        self,
        completed_ids: Iterable[str] = (),
        *,
        running_ids: Iterable[str] = (),
        blocked_ids: Iterable[str] = (),
    ) -> tuple[WorkerAssignment, ...]:
        """Return assignments whose dependencies are all completed.

        Results are ordered by the original plan order.  A running or blocked
        assignment is never returned, so callers can safely call this after
        out-of-order worker results arrive.
        """

        completed = _ids(completed_ids, "completed_ids")
        running = _ids(running_ids, "running_ids")
        blocked = _ids(blocked_ids, "blocked_ids")
        known = set(self._order)
        unknown = (completed | running | blocked) - known
        if unknown:
            raise DependencyGraphError(
                "状态集合包含未知 assignment：" + ", ".join(sorted(unknown))
            )
        overlap = (
            (completed & running)
            | (completed & blocked)
            | (running & blocked)
        )
        if overlap:
            raise DependencyGraphError(
                "completed/running/blocked 必须互斥：" + ", ".join(sorted(overlap))
            )
        return tuple(
            self._nodes[assignment_id].assignment
            for assignment_id in self._order
            if assignment_id not in completed
            and assignment_id not in running
            and assignment_id not in blocked
            and all(dependency in completed
                    for dependency in self._dependencies[assignment_id])
        )

    # ``runnable`` is a friendly alias used by callers that model scheduling
    # rather than graph theory.
    runnable = ready

    def execution_waves(self) -> tuple[tuple[WorkerAssignment, ...], ...]:
        """Return dependency waves; each wave is dependency-ready as a whole."""

        completed: set[str] = set()
        waves: list[tuple[WorkerAssignment, ...]] = []
        while len(completed) < len(self):
            wave = self.ready(completed)
            if not wave:
                raise DependencyGraphError("DAG 无法推进：存在未解决依赖。")
            waves.append(wave)
            completed.update(item.assignment_id for item in wave)
        return tuple(waves)

    def safe_parallel_group(
        self,
        assignments: Iterable[WorkerAssignment],
    ) -> tuple[WorkerAssignment, ...]:
        """Filter a candidate group to independently safe read-only workers.

        Session 4 intentionally permits parallel Researcher work only.  Coder
        and Tester remain serial even when their graph dependencies happen to
        be empty; this protects the shared workspace and fixed verification
        order.
        """

        requested = tuple(assignments)
        if any(not isinstance(item, WorkerAssignment) for item in requested):
            raise DependencyGraphError(
                "parallel candidates 只能包含 WorkerAssignment。"
            )
        candidates = tuple(self.get(item.assignment_id) for item in requested)
        result: list[WorkerAssignment] = []
        for item in candidates:
            if not self._is_parallel_eligible(item):
                continue
            if all(self.can_run_in_parallel(item, other) for other in result):
                result.append(item)
        return tuple(result)

    def can_run_in_parallel(
        self,
        left: WorkerAssignment,
        right: WorkerAssignment,
    ) -> bool:
        """Return whether two assignments satisfy Session 4 safety rules."""

        left = self.get(left.assignment_id)
        right = self.get(right.assignment_id)
        if left.assignment_id == right.assignment_id:
            return False
        if not self._is_parallel_eligible(left) or not self._is_parallel_eligible(right):
            return False
        if (
            left.assignment_id in self._ancestors[right.assignment_id]
            or right.assignment_id in self._ancestors[left.assignment_id]
        ):
            return False
        if set(left.shared_resources) & set(right.shared_resources):
            return False
        if set(left.write_targets) & set(right.write_targets):
            return False
        if left.write_targets or right.write_targets:
            return False
        return True

    # Alias for code that reads the method as a policy check.
    parallel_safe = can_run_in_parallel

    def parallel_groups(
        self,
        completed_ids: Iterable[str] = (),
    ) -> tuple[tuple[WorkerAssignment, ...], ...]:
        """Partition currently-ready work into safe parallel and serial groups."""

        ready = self.ready(completed_ids)
        parallel = self.safe_parallel_group(ready)
        parallel_ids = {item.assignment_id for item in parallel}
        groups: list[tuple[WorkerAssignment, ...]] = []
        if parallel:
            groups.append(parallel)
        # Every non-researcher is a one-item group, preserving plan order.
        groups.extend(
            (item,)
            for item in ready
            if item.assignment_id not in parallel_ids
        )
        return tuple(groups)

    def critical_path(
        self,
        durations: Mapping[str, float] | None = None,
    ) -> tuple[str, ...]:
        """Return the longest dependency path using declared durations."""

        duration_map = {
            item.assignment_id: item.estimated_seconds for item in self._assignments
        }
        if durations is not None:
            unknown = set(durations) - set(self._order)
            if unknown:
                raise DependencyGraphError(
                    "durations 包含未知 assignment：" + ", ".join(sorted(unknown))
                )
            for assignment_id, value in durations.items():
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(value)
                    or value <= 0
                ):
                    raise DependencyGraphError(
                        f"duration {assignment_id} 必须大于 0。"
                    )
                duration_map[assignment_id] = float(value)

        best: dict[str, tuple[float, tuple[str, ...]]] = {}
        for assignment_id in self._topological_order:
            dependencies = self._dependencies[assignment_id]
            if not dependencies:
                best[assignment_id] = (
                    duration_map[assignment_id],
                    (assignment_id,),
                )
                continue
            predecessor = max(
                (best[dependency] for dependency in dependencies),
                key=lambda value: (value[0], tuple(-self._order.index(item)
                                                    for item in value[1])),
            )
            best[assignment_id] = (
                predecessor[0] + duration_map[assignment_id],
                (*predecessor[1], assignment_id),
            )
        return max(
            best.values(),
            key=lambda value: (value[0], tuple(-self._order.index(item)
                                                for item in value[1])),
        )[1]

    def as_dict(self) -> dict[str, object]:
        return {
            "assignment_ids": list(self.assignment_ids),
            "topological_order": list(self.topological_order()),
            "dependencies": {
                assignment_id: list(self._dependencies[assignment_id])
                for assignment_id in self.assignment_ids
            },
            "critical_path": list(self.critical_path()),
        }

    @staticmethod
    def _is_parallel_eligible(assignment: WorkerAssignment) -> bool:
        return (
            assignment.role == "researcher"
            and not assignment.role_spec.boundary.can_write
            and not assignment.write_targets
        )

    def _validate_acyclic(self) -> tuple[str, ...]:
        remaining = {
            assignment_id: len(self._dependencies[assignment_id])
            for assignment_id in self._order
        }
        queue = deque(assignment_id for assignment_id in self._order if remaining[assignment_id] == 0)
        result: list[str] = []
        while queue:
            current = queue.popleft()
            result.append(current)
            for dependent in self._dependents[current]:
                remaining[dependent] -= 1
                if remaining[dependent] == 0:
                    queue.append(dependent)
        if len(result) != len(self._order):
            cyclic = [assignment_id for assignment_id in self._order
                       if remaining[assignment_id] > 0]
            raise DependencyGraphError(
                "依赖图包含环：" + ", ".join(cyclic) + "。"
            )
        return tuple(result)


__all__ = [
    "DependencyGraph",
    "DependencyGraphError",
    "DependencyNode",
]
