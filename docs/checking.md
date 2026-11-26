# Checking ／ 检查清单、证据与放行

检查的目的是「这一版香精能不能交出去」，不是「打多少分」。所以这里只有要求、证据和放行结论，没有评分。

## 1. 规则从哪来

规则文件是 `resources/审查/香精审查规则_轻量版.json`，由 `app/assets/rules.py` 读取，只读不改。里面有三层默认项：

- 审查品类默认项：18 个品类，各自一套指标与子项。品类由基质或最终产品文字推断（`CATEGORY_ALIASES`），推断不出就留空。
- 通用默认项：IFRA、SDS、规格书，任何项目都要。
- 条件默认项：闪点、COA、过敏原、额外要求、复湿再释放等，只在文字里出现相应线索时才生成。

市场按 `market_defaults` 生成一条 R_MARKET，子项用市场的正式名称（如「中国大陆」）；市场代码不在字典里时记一条 coverage 待确认，不猜。

规则文件的 `dispatch_rules.no_numeric_defaults` 明确禁止自动判定数值。所以这里只生成「要测什么、按什么口径记录」，不写「合格线 12」。合格线由部门回执或客户标准给出。

## 2. 生成清单

`checking.build.build(rules, context)` 输出三样：要求列表、coverage、按部门分组。

生成时机：目标位进入 checking 后，由 `build_checks` 动作触发。参数只有审查品类与市场，都可以留空：

- 品类留空：只出通用、市场、客户要求，coverage 记 `review_category_missing`。
- 市场留空：coverage 记 `market_missing`，销售地法规待定。
- 客户原话里的要求：作为 R_EXTRA 单独成条，来源记 customer，原文进 origin_text。

重新生成会新增一版清单（revision +1），旧版保留。放行只认最新版。

## 3. 证据与核销

`checking.evidence.match` 按「香精 + 配方版本 + 指标 + 子项 + 条件键」找历史证据，命中的直接改状态：

- 结论通过的证据 → passed，备注写回来源。
- 结论不通过的证据 → failed。
- 多条证据结论冲突 → needs_review，交人工判断，不自动取最新一条。
- 没有证据 → unverified。

数据来源只有两处：部门回执（`apply_receipt`）和人工补录。两者都写 `evidence`，都带香精与版本，所以同一款香精第二次做检查时不用重复送检。

这也是「二查」能成立的原因：开发子方向验收入库时已经测过这一版香精，父目标位重新生成清单时会当场核销，只需要补交付范围特有的项。

## 4. 派发

`dispatch_checks` 只派 unverified 的项，按部门分组，每个部门一条任务，spec 里带这一组的 requirement_ids。已经 passed 的项不再打扰部门。

全部已核销时不再派任务，直接提示「没有待派发的要求，现有证据已覆盖」。

## 5. 放行判定

`checking.release.decide(action, requirements)` 是纯函数，四种 action 的严格程度不同：

- warehouse、formal、resend：任何未核销项都算阻断。
- initial：只有 `deferral = blocked` 的未核销项才阻断，其余可暂缓，但必须在放行备注里写明。
- 任何 action：failed 阻断；needs_review 阻断；全部不适用时阻断，要求确认依据。

不可暂缓的指标是 IFRA、市场法规、过敏原、额外要求（`DEFERRAL_BLOCKED`）。理由很直接：这几项事后补不了，寄出去的样可能直接违规。

放行结果写 `release_decision`，通过的也写，未通过的也写。目标位阶段不由放行结果直接改：

- initial 通过 → 进 shipping，寄样回执后回到 checking。
- formal 通过 → 进 shipping，寄样回执后 complete。
- warehouse 通过 → 仍在 checking；派发入库、确认入库都在这一阶段内完成。

入库确认时可以给香精一个正式编号与版本（试作编号 → 正式编号）。这是改名，不是换配方，所以同一版本已有的证据会一起改键，父目标位的二查才能直接复用。如果确实换了配方，应该先重新生成清单再入库，旧证据不会被带过去。

## 6. 清单里能看到什么

页面展开清单时按部门列，每条显示指标名与子项、判定口径（来自规则文件的 record_hint）、回执备注、状态。coverage 单独显示，用来说明「为什么少了几项」。

不显示分数，也不显示「风险等级」——规则文件没有这两个东西，编出来只会误导。

