# Eval Experiment Log

Session05 开始，Eval 结果必须按实验记录，而不是只记录“感觉变好了”。

## 实验纪律

- 每轮只修改一个变量：Prompt、工具描述、模型参数或代码逻辑不能混改。
- Baseline 和 Candidate 使用相同的 case、模型、预算和验证方式。
- 先记录假设，再运行实验；实验结束后同时检查总体结果和能力分桶。
- 总体通过率上升但 ambiguity、injection 或 tool-use 下降时，视为回归。
- 真实大模型 Eval 会产生 token/费用；没有明确实验授权时只做静态分析和框架测试。

## 推荐命令

```bash
# 运行一组真实实验（会调用大模型，需明确授权）
make UV=/home/gxq/.local/bin/uv eval SUITE=core EXPERIMENT=w09-baseline

# 比较两份已经生成的报告，不会调用大模型
make UV=/home/gxq/.local/bin/uv eval-compare \
  BASELINE=logs/evals/w09-baseline.json \
  CANDIDATE=logs/evals/w09-experiment-001.json
```

## 实验记录模板

复制下面的模板，使用唯一的实验编号：

```markdown
## Experiment NNN

### Hypothesis

哪一个失败桶的什么根因，预计通过什么单变量改动改善？

### Change

只修改了什么？明确列出没有修改的变量。

### Baseline

- Report:
- Overall objective pass rate:
- Tool use:
- Reasoning:
- Ambiguity:
- Injection:
- Subjective/Judge:
- Cost / tokens / cache read ratio:

### Result

- Report:
- Overall objective pass rate:
- Bucket deltas:
- Failure taxonomy deltas:
- Cost / tokens / cache read ratio:

### Regression Check

是否有局部能力下降？失败类别是否增加？

### Conclusion

Keep / Revert / Need another experiment，以及原因。
```

## Session05 基础设施

已接入失败分类、能力分桶、token/cache 用量汇总和报告比较工具。
本次代码实现没有运行真实大模型 Eval；实验数据应由后续明确授权的实验命令填入。
