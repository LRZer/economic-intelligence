# DeepSeek 一次性真实接口核验

此入口检验真实HTTP调用及同一套有据摘要解析／引用校验。默认模式是离线预检；mock单元测试通过不能证明真实接口、余额或当前密钥可用。

## 用户本人操作

Windows：桌面已有 `api_key.md` 时，双击项目根目录 `test-deepseek-once.cmd`。窗口说明发送范围；**本人按回车才会读取该文件并发出一次请求**，输入其他内容取消。不需要把key发到对话，也不需要复制到项目配置。本人启动才会使用真实凭据，助手不会执行这一步。

也可由本人在本机PowerShell执行：

```powershell
.\.venv\Scripts\python.exe scripts\deepseek_live_check.py --live
```

如果密钥文件有多个key，必须有明确的DeepSeek节标题／标签，否则程序停止并不发送。文件最多64KiB，只在内存提取唯一凭据；不会修改原文件、写入环境变量或创建持久凭据配置。文件读取与请求仅发生在本人确认之后。

## 请求与费用边界

- 固定地址 `https://api.deepseek.com/chat/completions`，TLS校验开启，禁止HTTP重定向；认证只在Authorization头中。
- 模型 `deepseek-flash`，`thinking.type=disabled`，`stream=false`，`response_format.type=json_object`，输出最多512 tokens。
- 只有一条明确标注 `test_fixture` 的人工合成材料，不发送真实经济数据、个人资料、完整文件或聊天记录。
- 输入保守估计上限2048 tokens；按2026-10-04官方峰值价输入$0.3／百万、输出$1.2／百万，估算至多$0.0012288。价格可能变化，估算不代表实际账单。
- 本次累计人民币10元预算已获批准，不充值、不订阅。硬限制一次请求，不自动重试；原子尝试标记阻止重复及并发窗口。超时可能已被服务接收，因此不自动再次发送。

官方来源：[模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)、[Chat Completions参数](https://api-docs.deepseek.com/api/create-chat-completion/)。新默认模型替换原有据摘要的旧模型名，并显式关闭思考模式；不据此声称旧别名一定会被拒绝。

## 脱敏结果

本人触发后的结果：`reports/deepseek-live-check.json`。只记录状态、HTTP状态码、尝试次数、token用量（服务返回时）、耗时和结构／引用校验布尔值；不记录key、响应正文、Markdown密钥文件内容或请求头。`passed`须同时满足HTTP成功、有效完整JSON、引用给定证据且生成文字不含伪造数字；这不证明摘要所有语义正确或模型经济分析有效。

`authentication`、`balance`、`rate_limit`、`invalid_request`、`transport`等分类是脱敏诊断，不输出服务错误正文。非交互运行不读取key、不发送，也不覆盖真实结果。已有尝试时程序拒绝自动重测；应先人工核对回执与服务账单，不能通过删标记或自动重试掩盖失败。

默认预检：

```powershell
.\.venv\Scripts\python.exe scripts\deepseek_live_check.py
```

只检查文件是否存在并保存无密钥请求预览到 `reports/deepseek-preflight.json`。测试报告和尝试标记均已被Git忽略，不上传用户运行证据；CI只运行合成凭据／mock HTTP回归。

## 本地回归

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_ai.py tests/test_grounded_ai.py tests/test_deepseek_live_check.py tests/china/test_app.py
```

覆盖预检／非交互／取消不读key，合成文件解析、单次发送、并发防重复、只授权头含凭据、不跳转、不重试、错误脱敏、原文件与环境不变、输出上限，以及旧轻量应用默认付费关闭和官方请求参数。真实请求目前尚未由用户触发；未把mock结果计为真实通过。

本轮本机：43项最终接口回归通过，另一次含既有摘要UI的44项回归通过；Ruff、8文件mypy、Node和Bandit中高门槛通过。测试使用合成凭据与mock HTTP，此后用户本人已触发一次合成材料连通检查成功；助手未触发、不重试，不作为业务生成质量证据。那次预算已结束，本阶段无新增付费请求，真实密钥与本地回执不发布。见[机器可读状态](validation/deepseek-regression-status.json)、[最终日志](validation/deepseek-final-tests.log)和[安装包审计](validation/deepseek-build-artifact-audit.json)。
