.PHONY: agent web sandbox-build help eval eval-case eval-core eval-regression eval-smoke eval-judge eval-session04 eval-compare eval-full eval-all

UV ?= uv
EVAL_RUNNER := $(UV) run python evals/run.py
WEB_HOST ?= 127.0.0.1
WEB_PORT ?= 3000
WEB_WORKDIR ?= ..
WEB_REPOSITORY_WORKTREE ?= true
EXECUTOR_BACKEND ?= docker
SANDBOX_IMAGE ?= agent-mini-sandbox:local

# Eval 默认运行 core；传入 CASE 后，CASE 会优先于 SUITE。
SUITE ?= core
CASE ?=
EXPERIMENT ?= w09-$(SUITE)
REPORT_FILE ?=
BASELINE ?=
CANDIDATE ?=
ROUTER ?= off
CACHE ?= on

CASE_ARGS := $(foreach case_name,$(CASE),--case "$(case_name)")
EVAL_SELECTOR := $(if $(strip $(CASE)),$(CASE_ARGS),--suite "$(SUITE)")
REPORT_ARGS := $(if $(strip $(REPORT_FILE)),--report-file "$(REPORT_FILE)")

agent:
	uv run python -m src.cli "$(TASK)" $(OPTIONS)

web:
	AGENT_WORKDIR="$(WEB_WORKDIR)" AGENT_REPOSITORY_WORKTREE="$(WEB_REPOSITORY_WORKTREE)" AGENT_EXECUTOR_BACKEND="$(EXECUTOR_BACKEND)" AGENT_DOCKER_IMAGE="$(SANDBOX_IMAGE)" $(UV) run uvicorn src.web.app:app --host "$(WEB_HOST)" --port "$(WEB_PORT)" --reload

sandbox-build:
	docker build --tag "$(SANDBOX_IMAGE)" --file docker/sandbox.Dockerfile .

help:
	@echo "agent-mini commands:"
	@echo "  make agent TASK='...' [OPTIONS='...']"
	@echo "  make sandbox-build             构建 Docker Sandbox 镜像"
	@echo "  make web [WEB_WORKDIR=..]       启动 FastAPI + SSE Demo（默认 Docker Executor）"
	@echo "  make eval                         运行 core（默认 22 个）"
	@echo "  make eval-case CASE=name          运行指定 case"
	@echo "  make eval-core                    运行 core（22 个）"
	@echo "  make eval-regression              运行 regression（6 个）"
	@echo "  make eval-smoke                   运行 smoke（6 个）"
	@echo "  make eval-judge                   运行 Judge（5 个）"
	@echo "  make eval-session04              运行 Session04 行为约束（4 个）"
	@echo "  make eval-compare BASELINE=... CANDIDATE=...  对比两份报告（不调用模型）"
	@echo "  make eval-full 或 make eval-all   运行全量（32 个）"
	@echo ""
	@echo "可选变量：SUITE=core CASE=name EXPERIMENT=name REPORT_FILE=path ROUTER=off|on CACHE=off|on UV=uv"

eval:
	$(EVAL_RUNNER) $(EVAL_SELECTOR) --experiment "$(EXPERIMENT)" --router "$(ROUTER)" --cache "$(CACHE)" $(REPORT_ARGS)

eval-case:
	@test -n "$(strip $(CASE))" || (echo "用法: make eval-case CASE=code_review_report"; exit 2)
	$(MAKE) eval CASE="$(CASE)" EXPERIMENT="$(EXPERIMENT)" REPORT_FILE="$(REPORT_FILE)" CACHE="$(CACHE)"

eval-core:
	$(MAKE) eval SUITE=core

eval-regression:
	$(MAKE) eval SUITE=regression

eval-smoke:
	$(MAKE) eval SUITE=smoke

eval-judge:
	$(MAKE) eval SUITE=judge CASE="ambiguous_tradeoff explain_architecture explain_module write_readme code_review_report"

eval-session04:
	$(MAKE) eval SUITE=session04

eval-compare:
	@test -n "$(strip $(BASELINE))" || (echo "缺少 BASELINE=path"; exit 2)
	@test -n "$(strip $(CANDIDATE))" || (echo "缺少 CANDIDATE=path"; exit 2)
	$(UV) run python -m evals.compare --baseline "$(BASELINE)" --candidate "$(CANDIDATE)"

eval-full:
	$(MAKE) eval SUITE=full

eval-all:
	$(MAKE) eval SUITE=all
