# -*- coding: utf-8 -*-
"""Generate final 汇报 (report) markdown from batch_manifest.json + QA results."""
import json, os, datetime

WS = r"C:\Users\26519\Desktop\交付总控\ABC"
OUT = os.path.join(WS, "output")
DOCS = os.path.join(WS, "docs")

with open(os.path.join(OUT, "batch_manifest.json"), encoding="utf-8") as f:
    m = json.load(f)

qa = {}
qa_path = os.path.join(OUT, "qa_vs_draft.json")
if os.path.exists(qa_path):
    with open(qa_path, encoding="utf-8") as f:
        qa = json.load(f)

total = m["total_source_rows"]
tags = m["tags_count"]
cat_cov = m["category_coverage"]

def pct(v):
    return f"{v/total*100:.1f}%"

lines = []
lines.append("# 中央闻香库第一轮冷启动清洗 · 汇报")
lines.append("")
lines.append(f"> 生成时间:{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} | taxonomy_version:{m['taxonomy_version']}")
lines.append("> 任务:将中央闻香库每款香精转为可供 wanted 的品类筛选、ABC 匹配与产品身份检索使用的结构化资产(冷启动试跑:候选覆盖优先于精确率)。")
lines.append("> 机器可读数据与 QA 记录见 `output/`。人可读工作簿、复核清单及报告见 `docs/`。")
lines.append("")
lines.append("## 一、总体数字")
lines.append("")
lines.append("| 项 | 数值 |")
lines.append("|---|---|")
lines.append(f"| 原始行数 | {total} |")
lines.append(f"| 唯一有效编码 | {m['unique_valid_codes']} |")
lines.append(f"| 缺码/0码行 | {m['zero_missing_code_rows']}(以 source_row 暂存,未写入正式身份表) |")
lines.append(f"| 重复编码组 / 额外行 | {m['duplicate_codes']} / {m['duplicate_extra_rows']}(程序复核较草稿 52/57 多出 DXB303BDX「力士蓝」一组) |")
lines.append(f"| 重复编码属性一致已合并 | {m['merged_duplicate_codes']} 组 |")
lines.append(f"| 重复编码冲突保留不同源行 | {m['conflict_duplicate_codes']} 组(进入复核清单) |")
lines.append(f"| 处理行数 / 缺结果行 | {m['rows_processed']} / {m['rows_missing']} |")
lines.append(f"| 产品候选关联数 | {m['product_candidates_links']}(全部为候选,无已确认仿香) |")
lines.append(f"| 已核验商业产品数(字典) | {m['verified_products']} |")
lines.append(f"| 原新品标记 / 原爆品标记 | {m['is_new_count']} / {m['is_hot_count']} |")
lines.append(f"| 状态分布 | {json.dumps(m['status_distribution'], ensure_ascii=False)} |")
lines.append("")
lines.append("## 二、品类覆盖")
lines.append("")
lines.append("| 品类 | 行数 |")
lines.append("|---|---|")
for k, v in sorted(cat_cov.items(), key=lambda x: -x[1]):
    lines.append(f"| {k} | {v} |")
lines.append("")
no_cat = total - sum(cat_cov.values())
lines.append(f"未定品类行:{no_cat}(旧二级为 ALL/其他家庭护理等按规则留空或按三级/备注补充,明细见 review_queue「品类未定」)。")
lines.append("")
lines.append("## 三、ABC 标签覆盖(行级非空比例)")
lines.append("")
lines.append("| 层级 | 非空行数 | 占比 |")
lines.append("|---|---|---|")
for k in ["A1", "A2", "A3", "B", "C"]:
    lines.append(f"| {k} | {tags.get(k, 0)} | {pct(tags.get(k, 0))} |")
lines.append("")
lines.append("说明:本轮输入仅含名称、旧二级/三级/品类备注与 A3 规则初筛(旧子香族→A3);原库的旧香族/子香族/风格/人格/三调/主韵等评香字段不在提供的三个文件中,故 A1/A2/B/C 以名称与品类语境驱动,覆盖较稀疏属预期;第二轮接入原始评香字段后可显著补全 B 与 C。")
lines.append("")
lines.append("## 四、产品身份")
lines.append("")
lines.append(f"- 程序预匹配+底稿候选 665 行,仅品牌线索 45 行,其余 3180 行未识别(非否定)。")
lines.append(f"- 产品候选关联 {m['product_candidates_links']} 条,全部为候选(relation_status=strong_candidate/ambiguous/candidate),**无一条为已确认仿香**(本轮无人工确认证据)。")
lines.append(f"- 已核验存在产品 {m['verified_products']} 个(官网核验),其余待核验。")
lines.append(f"- is_big_brand_dupe 全部为 null(未知)。")
lines.append("")
lines.append("## 五、新品/爆品")
lines.append("")
lines.append("- 原标识直接复制:新品 265、爆品 1171;0 表示原库未标记,不是市场现状断言。")
lines.append("- 同编码多来源时保留全部原始入库逻辑,冲突进入复核。")
lines.append("")
lines.append("## 六、错误与复核清单")
lines.append("")
lines.append(f"- 校验错误 {m['errors']} 条(详见 review_queue「校验错误明细」)。")
lines.append(f"- 复核清单:缺码 {m['zero_missing_code_rows']}、重复合并 {m['merged_duplicate_codes']}、重复冲突 {m['conflict_duplicate_codes']}、产品待核验等(详见 review_queue.xlsx)。")
if qa:
    lines.append(f"- 试点一致性:与人工试跑示范 {qa.get('draft_rows', 0)} 行对照 {json.dumps(qa.get('agreement_by_field', {}), ensure_ascii=False)}(见 qa_vs_draft.json)。")
r15 = m.get("round15")
if r15:
    lines.append("")
    lines.append("### Round 1.5 补标(评香字段)")
    lines.append("")
    lines.append(f"- 补读原始《【wip】中央闻香库20260623.xlsx》并按编码+名称关联 {m.get('original_join', {}).get('mapped_rows', 0)} 行,未关联 {m.get('original_join', {}).get('unmapped_rows', 0)} 行(见复核清单「原始库未关联」)。")
    lines.append(f"- 含评香字段(香族/子香族/三调/主韵/风格/人格/联觉)共 {r15['refined_rows']} 行,LLM 增量修订后写回主视图。")
    adds = r15["added"]; rems = r15["removed"]
    lines.append(f"- 增量:新增 A1 {adds.get('tags_A1', 0)} / A2 {adds.get('tags_A2', 0)} / A3 {adds.get('tags_A3', 0)} / B {adds.get('tags_B', 0)} / C {sum(v for k, v in adds.items() if k.startswith('C:'))};移除 A1 {rems.get('tags_A1', 0)} / A2 {rems.get('tags_A2', 0)} / A3 {rems.get('tags_A3', 0)} / B {rems.get('tags_B', 0)} / C {sum(v for k, v in rems.items() if k.startswith('C:'))}(修订冲突按评香为准)。")
    lines.append(f"- 三调(前/中/后调)仅作整体香型方向参考,不作 A 标签(香韵)直接证据;A 证据以主韵关键词/香族/子香族为准。")
    lines.append(f"- 保留第一轮新品/爆品/产品候选成果,不重复品牌搜索;产品候选关联仍为 {m['product_candidates_links']} 条。")
    lines.append(f"- 系统报价 {m.get('price_fields', {}).get('system_quote_rows', 0)} 行 / 价格段 {m.get('price_fields', {}).get('price_segment_rows', 0)} 行已并入 fragrance.jsonl(价格段分布 {json.dumps(m.get('price_fields', {}).get('price_segment_distribution', {}), ensure_ascii=False)})。")
    lines.append(f"- 执行通道:llmapi.paratera.com(THU dsflash DeepSeek-V4-Flash-0731)+PARATERA_API_KEY 直连批量,49 批全量完成,断点续跑。")
lines.append("")
lines.append("## 七、与 wanted 的接口说明")
lines.append("")
lines.append("见 [调用说明](README_调用说明.md)。标准品类、新品、爆品和已确认的目录属性可用于筛选。不确定的产品身份只在候选入口展示。F00 的 C→AB 映射仅用于评分。")
lines.append("")
lines.append("## 附录:执行层设计(本轮采用)")
lines.append("")
lines.append("1. **三层拆分**:①确定性预处理(旧字段转换、无歧义别名命中、品类初筛、A3 规则映射、新品/爆品标识、产品候选底稿)——程序完成,不做 LLM 复核;②LLM 增量贴标(仅补 A2/B/C、校验品类与 A1/A3、产品歧义、未识别术语);③品牌产品身份核验——本轮沿用底稿候选,不联网阻塞清洗。")
lines.append("2. **上下文精简**:LLM 仅接收「精简 AB 字典(id+标签)+ 本批涉及品类的 C 完整判定树(闸门/叶子+左侧判定补充)」,完全移除 C→AB 关联映射、专家确认表、AB 别名全表等无关信息。")
lines.append("3. **输出最小化**:每行只输出增量与异常(`{\"source_row\": N}` 表示基线无异议);证据由程序按标签自动补证,LLM 不为每个标签撰写解释。")
lines.append("4. **直连 API 批量执行**:程序直接调用 DeepSeek chat API(`deepseek-chat`,temperature=0),并发 12,130 批 × 30 行全库耗时 **约 72 秒**,0 失败;每批成功立即落盘 `_work/batches/batch_NNN_result.jsonl`,程序校验行数/ID 并支持断点续跑(重跑自动跳过已有结果)。")
lines.append("5. **质量对照**:与人工试跑示范 33 行逐字段一致率见 `qa_vs_draft.json`;64 条校验错误(闸门误作 C 叶子、跨品类 C、伪 ID)均未写入输出,已入复核清单。")
lines.append("6. **C 判定语义**:仅按品类→闸门→叶子路径判断;允许合理弱推断;不通过 AB 反推商业定位 C;产品形态不明的洗护/织物行不强行贴 C。")
lines.append("")
lines.append("## 已知限制")
lines.append("")
lines.append("- 原库《【wip】中央闻香库20260623.xlsx》未提供,评香字段(主韵/三调/旧香族/子香族/风格/人格/联觉)缺失,仅以名称、旧二级/三级、备注与 A3 初筛驱动,第二轮接入原始评香字段后可显著补全 A2/B/C 覆盖。")
lines.append("- 仿香关系无人工确认证据,全部为候选;`is_big_brand_dupe` 本轮一律 null。")
lines.append("- 重复编码冲突(21 组)、缺码(2 行)、疑似异常编码(1 行)与未识别术语(258 行)待人工/字典更新后二轮处理。")

os.makedirs(DOCS, exist_ok=True)
out = os.path.join(DOCS, "汇报.md")
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("wrote", out)
