# 运行、复算与可选发布

本文件区分已经存在的本地程序与需要自行部署的发布流程。仓库不会自动创建飞书文档、登记多维表格或推送群消息。

## 1. 运行环境

Python 3.10+，依赖版本见requirements.txt。本次验证使用Python 3.10、AkShare 1.18.88、pandas 2.3.3。PandaAI与lark-cli是可选外部工具，不属于pip依赖。

```bash
python -m pip install -r requirements.txt
python daily_report.py --date 2026-09-16
```

每个行情接口在独立子进程中执行，默认30秒超时；可用 `--timeout 20` 调整。取数按品种顺序执行，不无限重试。若只核验部分品种，可用 `--symbols AU0,M0,IF0`。

## 2. 输入和输出

- `raw/<run_id>/manifest.json`：输入目录索引、日期、来源、请求时间、版本、文件哈希和失败项。
- `raw/<run_id>/*.csv`：AkShare返回的行情表和合约规则表。
- `reports/daily_report_<date>_<run_id>.md`：完整可读报告。
- 同名XML：同一内容结构导出的飞书格式。
- `reports/meta_<date>_<run_id>.json`：结构化计算结果和证据状态。
- `reports/latest_meta.json`：最近一次运行结果；不是每日唯一发布记录。
- `snapshots/regime_<date>_<run_id>.csv`：用于对比的汇总快照。

每次运行保留独立结果，避免重新运行覆盖历史证据。stdout输出一个meta JSON，进度写入stderr。无有效品种时退出码2，并保留诊断报告；部分有效时仍可生成报告，缺失项和覆盖数必须一起阅读。

输出目录由 `--output-dir` 或 `FUTURES_HOME` 控制；不要依赖旧版固定日期文件名定位最新报告，应读取meta中的路径。

## 3. 离线复算

```bash
python daily_report.py --replay raw/<run_id>/manifest.json
```

重放先检查输入文件SHA256，再使用当前代码计算。当前代码可能与采集时不同，应对照manifest中的代码哈希；同一输入在不同公式版本下的差异不能叫作行情变化。

`--legacy-snapshot` 是单独的旧快照预览路径，不属于完整复算，因为旧CSV没有OHLC、均线证据及历史规则。

## 4. 账户查询

`--account` 查询当前Panda持仓。失败或未知不能显示无持仓；挂单未查询。历史日报不会自动混入黄金实时价。

黄金监控脚本要求可识别的 `equity` 权益字段，只处理配置的AU2612合约。其他黄金合约、多条无法合并的持仓或含义不明的字段会明确报错。该字段契约尚未在当前机器连接真实Panda账户验证，不得宣称已完成账户集成验收。

## 5. 飞书导入

本次查阅的本机lark-cli使用 `docs +create`；旧文档中的 `docs +script --command parse` 在本机CLI中不可用。使用前通过以下入口阅读与安装版本匹配的说明：

```bash
lark-cli skills read lark-doc
lark-cli docs +create --help
```

XML标签使用该CLI文档支持的title、h1/h2、p及table结构。本地回归测试检查XML能解析、文本正确转义，以及数据与报告一致；这不等于已经在线验证飞书渲染或发布成功。

若需要发布，先取得meta中的XML相对路径，再按当前CLI说明创建文档。`--content @file` 需位于当前工作目录内。较长报告应按CLI长文档流程分节写入，以免受远端块数限制。本文不保留未经本机版本确认的多维表格或消息字段示例。

## 6. 调度和去重

调度、交易所日历和发布事务尚未实现。Windows可用任务计划程序，其他环境可用适合该平台的调度器；任务应在源站日线更新后运行，不能把“工作日”当作“交易日”。

发布若要自动化，至少应持久化交易日、内容版本、文档ID、表格记录ID和消息ID。创建文档后再查表，不能避免重复建文档；消息幂等键也不能替文档创建去重。现有config示例仅为部署设计参考，不由Python程序自动加载。

## 7. 运行故障

输入超时或缺失：先看manifest与报告的异常表，必要时只补取失败品种；不要将部分样本冒充完整覆盖。

行情日期不匹配：核对研究日及源站更新状况，避免为了通过检查直接改写日期。前结算缺失：保留该字段未知，不能悄悄改用前收盘。

规则接口失败：环境分析可以继续，仓位与保证金保持未知。账户失败：不影响公开行情分析，但不能继续出账户安全结论。

raw、reports和snapshots默认不提交Git。分享结果前清除账户信息，保留研究日期、来源、覆盖范围和证据状态。
