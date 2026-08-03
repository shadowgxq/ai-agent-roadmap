# API Docs

`docs/api/` 存放使用方项目的接口契约和联调说明。模板只保留入口规则，不包含真实业务接口。

## 内容

- OpenAPI/Swagger、接口清单、request/response schema。
- 参数、分页、错误码、鉴权、权限和 mock 约定。
- 联调说明、接口变更记录，以及影响前端行为的补充说明。

## 不放

- PRD、设计稿全文、前端组件规范或编码规范。
- 当前执行状态、临时计划、agent 过程记录或调试日志。
- 密钥、token、生产环境凭据或真实用户数据。

## 结构

```text
docs/api/
  README.md
  contracts.md
```

接口较多时，可按需增加 `mocks/`、`changelog.md`。

## 维护规则

- 有 OpenAPI/Swagger 时，以它为主来源。
- 临时补充应标明来源和待确认状态。
- 接口变更影响前端时，同步关联 PRD、OpenSpec 或实现任务。
- 不预写未确认接口。
