import asyncio
import json
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from .runtime import WorkflowRuntime
from .state import WorkflowState


class ParallelTask(BaseModel):
    """一个可以独立执行的模型任务。"""

    name: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    user_prompt: str = Field(min_length=1)
    max_tokens: int = Field(default=1200, gt=0)


class ParallelResult(BaseModel):
    """单个并行任务的执行结果。"""

    name: str
    output: str


class ParallelizationState(WorkflowState):
    """Parallelization Workflow 保存的 Worker 中间结果。"""

    worker_results: list[ParallelResult] = Field(default_factory=list)


VoteChoice = Literal["approve", "reject"]


class VoteDecision(BaseModel):
    """单个 Voter 返回的结构化判断。"""

    choice: VoteChoice
    reason: str = Field(min_length=1)


class VoteResult(VoteDecision):
    """带有 Voter 身份的投票结果。"""

    voter: str = Field(min_length=1)


class VotingState(WorkflowState):
    """Voting Workflow 保存的独立投票和多数决定。"""

    votes: list[VoteResult] = Field(default_factory=list)
    vote_decision: VoteChoice | None = None


class StructuredVoteError(RuntimeError):
    """Voter 多次未能返回有效的结构化投票结果。"""


def create_review_tasks(
    task: str,
    *,
    max_tokens: int = 1200,
) -> list[ParallelTask]:
    """把一次代码评审确定性地拆成三个互不依赖的检查维度。"""
    return [
        ParallelTask(
            name="correctness",
            system_prompt=(
                "你是代码正确性评审者。只检查功能逻辑、边界情况、"
                "错误处理以及是否满足任务要求，并给出具体依据。"
            ),
            user_prompt=task,
            max_tokens=max_tokens,
        ),
        ParallelTask(
            name="security",
            system_prompt=(
                "你是代码安全评审者。只检查输入信任边界、注入、"
                "权限、敏感信息和资源滥用风险，并给出具体依据。"
            ),
            user_prompt=task,
            max_tokens=max_tokens,
        ),
        ParallelTask(
            name="maintainability",
            system_prompt=(
                "你是代码可维护性评审者。只检查可读性、复杂度、"
                "重复逻辑、接口设计和后续修改风险，并给出具体依据。"
            ),
            user_prompt=task,
            max_tokens=max_tokens,
        ),
    ]


async def run_worker(
    runtime: WorkflowRuntime,
    task: ParallelTask,
) -> ParallelResult:
    """执行一个独立模型任务，并保留任务名称与输出的对应关系。"""
    output = await runtime.complete(
        step_name=f"worker-{task.name}",
        system_prompt=task.system_prompt,
        user_prompt=task.user_prompt,
        max_tokens=task.max_tokens,
    )
    return ParallelResult(name=task.name, output=output)


async def run_workers(
    runtime: WorkflowRuntime,
    tasks: list[ParallelTask],
) -> list[ParallelResult]:
    """严格模式并发执行全部任务，任意 Worker 失败时直接抛出异常。"""
    if not tasks:
        raise ValueError("并行任务列表不能为空")

    names = [task.name for task in tasks]
    if len(names) != len(set(names)):
        raise ValueError("并行任务名称不能重复")

    results = await asyncio.gather(
        *(run_worker(runtime, task) for task in tasks)
    )
    return list(results)


async def aggregate_results(
    runtime: WorkflowRuntime,
    state: ParallelizationState,
    results: list[ParallelResult],
    *,
    max_tokens: int = 1600,
) -> str:
    """去重并整合多个 Worker 的独立分析结果。"""
    if not results:
        raise ValueError("没有可汇总的 Worker 结果")

    serialized_results = json.dumps(
        [result.model_dump() for result in results],
        ensure_ascii=False,
        indent=2,
    )
    state.status = "summarizing"
    return await runtime.complete(
        step_name="aggregator",
        system_prompt=(
            "你负责汇总多个独立代码评审者的结果。"
            "合并重复问题，保留具体依据，明确存在冲突的判断，"
            "并按严重程度组织最终评审结论。"
            "只能依据 Worker 提供的内容，不要虚构新的代码问题。"
        ),
        user_prompt=(
            f"原始评审任务：\n{state.task}\n\n"
            f"Worker 结果：\n{serialized_results}"
        ),
        max_tokens=max_tokens,
    )


async def run_parallelization(
    runtime: WorkflowRuntime,
    state: ParallelizationState,
    *,
    worker_max_tokens: int = 1200,
    aggregator_max_tokens: int = 1600,
) -> ParallelizationState:
    """并发执行三个评审 Worker，再串行汇总全部结果。"""
    try:
        state.status = "parallelizing"
        tasks = create_review_tasks(
            state.task,
            max_tokens=worker_max_tokens,
        )
        state.worker_results = await run_workers(runtime, tasks)
        state.summary = await aggregate_results(
            runtime,
            state,
            state.worker_results,
            max_tokens=aggregator_max_tokens,
        )
        state.status = "completed"
        return state
    except Exception:
        state.status = "failed"
        raise


def create_voting_tasks(
    task: str,
    *,
    voter_count: int = 3,
    max_tokens: int = 600,
) -> list[ParallelTask]:
    """创建奇数个使用相同验收标准的独立 Voter。"""
    if voter_count < 3 or voter_count % 2 == 0:
        raise ValueError("voter_count 必须是大于等于 3 的奇数")

    system_prompt = (
        "你是独立验收者。严格根据任务中明确给出的要求，"
        "判断当前方案或代码是否可以接受。"
        "存在功能错误、遗漏要求或明确风险时选择 reject，"
        "全部明确要求均满足时选择 approve。"
    )
    return [
        ParallelTask(
            name=f"judge-{index}",
            system_prompt=system_prompt,
            user_prompt=task,
            max_tokens=max_tokens,
        )
        for index in range(1, voter_count + 1)
    ]


async def run_voter(
    runtime: WorkflowRuntime,
    task: ParallelTask,
    *,
    max_parse_attempts: int = 2,
) -> VoteResult:
    """执行一个独立 Voter，并重试无效的结构化输出。"""
    if max_parse_attempts <= 0:
        raise ValueError("max_parse_attempts 必须大于 0")

    schema = json.dumps(
        VoteDecision.model_json_schema(),
        ensure_ascii=False,
    )
    base_prompt = (
        f"待判断任务：\n{task.user_prompt}\n\n"
        f"JSON Schema：\n{schema}"
    )
    previous_output = ""
    parse_error = ""

    for attempt in range(1, max_parse_attempts + 1):
        if attempt == 1:
            user_prompt = base_prompt
        else:
            user_prompt = (
                f"{base_prompt}\n\n"
                f"上一次输出：\n{previous_output}\n\n"
                f"解析错误：\n{parse_error}\n\n"
                "请修正格式并重新输出完整 JSON。"
            )

        output = await runtime.complete(
            step_name=f"voter-{task.name}-parse-{attempt}",
            system_prompt=(
                f"{task.system_prompt}"
                "必须严格按照 JSON Schema 返回 JSON，"
                "不要输出 Markdown 或其他解释。"
            ),
            user_prompt=user_prompt,
            max_tokens=task.max_tokens,
        )
        try:
            decision = VoteDecision.model_validate_json(output)
        except ValidationError as exc:
            previous_output = output
            parse_error = str(exc)
            continue

        return VoteResult(voter=task.name, **decision.model_dump())

    raise StructuredVoteError(
        f"{task.name} 连续 {max_parse_attempts} 次返回无效结果"
    )


async def run_voters(
    runtime: WorkflowRuntime,
    tasks: list[ParallelTask],
    *,
    max_parse_attempts: int = 2,
) -> list[VoteResult]:
    """并发执行奇数个 Voter，不接受残缺的投票集合。"""
    if len(tasks) < 3 or len(tasks) % 2 == 0:
        raise ValueError("Voter 数量必须是大于等于 3 的奇数")

    names = [task.name for task in tasks]
    if len(names) != len(set(names)):
        raise ValueError("Voter 名称不能重复")

    votes = await asyncio.gather(
        *(
            run_voter(
                runtime,
                task,
                max_parse_attempts=max_parse_attempts,
            )
            for task in tasks
        )
    )
    return list(votes)


def decide_vote(votes: list[VoteResult]) -> VoteChoice:
    """使用 Python 计算多数票，不让模型改变最终决定。"""
    if len(votes) < 3 or len(votes) % 2 == 0:
        raise ValueError("投票结果数量必须是大于等于 3 的奇数")

    counts = Counter(vote.choice for vote in votes)
    if counts["approve"] > counts["reject"]:
        return "approve"
    return "reject"


def summarize_votes(
    votes: list[VoteResult],
    decision: VoteChoice,
) -> str:
    """确定性地汇总票数和每个 Voter 的判断理由。"""
    counts = Counter(vote.choice for vote in votes)
    lines = [
        f"最终决定: {decision}",
        (
            "票数: "
            f"approve={counts['approve']}, "
            f"reject={counts['reject']}"
        ),
    ]
    lines.extend(
        f"- {vote.voter}: {vote.choice} - {vote.reason}"
        for vote in votes
    )
    return "\n".join(lines)


async def run_voting(
    runtime: WorkflowRuntime,
    state: VotingState,
    *,
    voter_count: int = 3,
    voter_max_tokens: int = 600,
    max_parse_attempts: int = 2,
) -> VotingState:
    """并发收集独立判断，再由 Python 计算多数票。"""
    try:
        state.status = "voting"
        tasks = create_voting_tasks(
            state.task,
            voter_count=voter_count,
            max_tokens=voter_max_tokens,
        )
        state.votes = await run_voters(
            runtime,
            tasks,
            max_parse_attempts=max_parse_attempts,
        )
        decision = decide_vote(state.votes)
        state.vote_decision = decision
        state.summary = summarize_votes(
            state.votes,
            decision,
        )
        state.status = "completed"
        return state
    except Exception:
        state.status = "failed"
        raise
