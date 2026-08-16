README 事实基准：

- 项目是一个把逗号分隔文本转换成 JSON 数组的 Python CLI。
- 入口命令是 `python -m src.cli input.csv`。
- 输入文件必须包含表头；每行输出一个对象，字段名来自表头。
- `--pretty` 会使用缩进格式输出 JSON；默认输出紧凑 JSON。
- 项目只依赖 Python 3.12+ 标准库，不应声称需要网络服务或数据库。
- 示例应展示一个包含 name 和 city 两列的 CSV 输入及对应 JSON 输出。
