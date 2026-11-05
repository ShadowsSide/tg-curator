<!--
PR 请提到 DEV 分支；main 只通过 DEV → main 的 PR 更新。
Please target the DEV branch; main is only updated through DEV → main PRs.
-->

## 改了什么 / What changed

<!-- 按用户能感觉到的变化写，每条一行；修 issue 的话写 Fixes #123 -->
<!-- Describe what users will notice, one line each; for an issue, add Fixes #123 -->

-

## 为什么 / Why

<!-- 之前哪里不对、在什么情况下出问题 / What was wrong before, and when it showed up -->

## 验证 / How it was tested

- [ ] 全部测试通过 / All tests pass：`for f in tests/test_*.py tests/live_*.py; do .venv/bin/python "$f" || echo "FAILED: $f"; done`
- [ ] 静态检查通过 / Lint passes：`.venv/bin/python -m pyflakes bot tests`
- [ ] 新增或修改的测试在改动前的代码上会失败 / New or changed tests fail on the code before this change
- [ ] 在真实 Telegram 里试过（改了用户能看到的行为时）/ Tried in real Telegram (for user-visible changes)：

<!-- 写清楚试了哪些操作、结果怎样 / List what you tried and what happened -->

## 影响与回滚 / Impact and rollback

<!--
- 数据库：有没有新列、新表？旧库能否自动升级（db.MIGRATIONS）？/ Database: new columns or tables? Do old databases upgrade (db.MIGRATIONS)?
- 配置：有没有新的或改了含义的环境变量？/ Settings: any new environment variables, or changed meanings?
- 出问题时回滚到哪个提交 / Which commit to roll back to if something goes wrong
-->

## 检查清单 / Checklist

- [ ] 新文案同时有中文和英文（`bot/i18n.py`）/ New texts exist in both Chinese and English (`bot/i18n.py`)
- [ ] 新配置项写进了 `README.md`、`README.en.md` 和两个 `.env` 示例 / New settings are in `README.md`, `README.en.md` and both `.env` examples
- [ ] 处理函数只通过 Core 访问业务和数据，不直接用 `core.db` / Handlers go through Core, not `core.db`
- [ ] 提交已签名（main 的保护规则要求）/ Commits are signed (required by the main branch ruleset)
- [ ] 没有提交 token、`.env` 或其他敏感文件 / No tokens, `.env` or other secrets committed
