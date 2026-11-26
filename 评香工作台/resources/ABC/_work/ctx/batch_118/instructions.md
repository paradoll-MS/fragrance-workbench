# 中央闻香库 第一轮冷启动 · LLM 批次判定指令(v3 修正模式)

你是「中央闻香库」的标签判定员。程序已为每个批次中的每条记录生成了**基线结果**(`baseline`,来自确定性规则:品类初筛、旧香族→A3、名称→AB 别名命中、产品候选底稿)。你的任务:逐行**审查基线并输出修正**(判定 A2/B/C、校验品类与 A1/A3、处理歧义产品、补记未识别术语),而不是从头重写。本轮是冷启动试跑:有意义的候选覆盖优先于精确率,允许弱证据贴标;不强制填满;不制造无证据标签。

## 0. 必读输入文件(UTF-8)

- `C:\Users\26519\Desktop\交付总控\ABC\_work\ctx\shared\dicts.txt`: 合并字典,内含 categories.txt(应用品类)、tags_A.txt(A1/A2/A3 标签)、tags_B.txt(B 标签)、alias_AB.txt(AB 别名)、brands.txt(品牌)、c_decision.txt(C 判定补充)、legacy.txt(旧品类+旧香族转换)。
- `C:\Users\26519\Desktop\交付总控\ABC\_work\ctx\batch_XXX\C.txt`: 本批涉及的品类 C 子树(`id\t品类\t维度\t父ID\t标签\t节点类型\t完整标签路径`;只有 `叶子` 可输出)。
- `C:\Users\26519\Desktop\交付总控\ABC\_work\ctx\batch_XXX\products.txt`: 本批相关产品字典。
- `C:\Users\26519\Desktop\交付总控\ABC\_work\ctx\batch_XXX\batch.jsonl`: 每行 `{"input": {...}, "baseline": {...}}`(见 §3)。

## 1. 判断规则

### 1.1 品类
- 基线 `category_ids` 来自规则初筛,一般保留。仅在以下情况修正:
  - 旧二级为「其他家庭护理 & 其他家庭清洁」「其他个人护理 & 其他洗护沐」「天然香养」或为空且基线为空:结合三级/备注判断(对照 legacy.txt 的旧品类转换);仍无法确认则保持空并加 review_notes。
  - `ALL` 不自动写入全部品类,保持基线(通常为空)。
  - 二级与备注冲突:保留主品类,另一个放 `category_candidates`。
- 织物洗护一律 CAT_07;口腔护理 CAT_05(含唇部)。

### 1.2 A1 / A2 / A3 / B
- **A1**: 基线来自名称命中,一般保留。仅当命中明显错误(如长词被短词截断、营销词误当气味)时 `tags_A1_remove`,并把正确词用 `tags_A1_add` 补上(必须存在于 tags_A.txt 且层级为 A1)。不要把专有香水名(尼罗河花园、COCO小姐等)解析成香料。
- **A2**: 基线通常为空,由你判断。可从直接描述或有把握的 A1 语义得到(鲜茉莉→花香;柠檬→果香/柑橘;檀香→木质)。只输出 tags_A.txt 中层级 A2 的 ID。
- **A3**: 基线来自旧子香族/香族固定转换(`a3_id_screen`),**优先保留**;与名称明显冲突才 remove。没有基线的,若名称或主韵明确是结构/母型可 add 弱候选,但不要从单个原料构造复杂香调。
- **B**: 基线只在少数「香水/香氛」语境下预填了香水感。由你补充有把握的:如名称语境明显「香水/巴黎/香氛」且品类为洗护/织物 → B5_dd6d753261 香水感;「蓝色」→ B1_34ff19b8a8 冷色调(弱);「中性/独立/简约」类描述词 → 对应 B 标签。不要因「蓝/黑/白」名字普遍贴联觉;无把握留空。

### 1.3 C(品类内定位)
- 只用 `C.txt` 中该品类的叶子(节点类型=叶子),沿完整路径下钻。基线只预填了少量明确情形(空间香氛的茶/木质/东方/花香叶,洗护/织物的香水转化叶,个人香氛的花香西普/花香调叶)。
- 由你按语境补充/移除。参考 c_decision.txt 判定补充。没有明确或合理弱语义支持就留空,不发明标签。
- **不得把 C→AB 映射反推为 AB→C**(木质+麝香≠通勤商务);同一 A3 与 C 香调叶同义可分别贴标。
- 具体旧香调在该品类无对应叶子时,允许退回有充分语义支持的母型,否则留空。
- 仅品牌线索、无香气描述时 C 保持空。

### 1.4 产品身份
- 基线 `product_candidates` 来自程序底稿(名称/别名匹配),一般保留。需要你:
  - 把明显是歧义的候选(普通香韵名、短词、仅相似译名)改为 `relation_status: "ambiguous"`;
  - 基线漏掉的强线索(显式品牌+独特产品名、双语名)用 `product_candidates_add` 补上(引用 products.txt 的 product_id/brand_id;字典没有的,给候选名称并 `"is_new_product": true`);
  - 单独的「香奈儿」这类仅品牌名:不加产品,dupe_status 改 `brand_only`;
  - 「绿茶」≠雅顿绿茶;「蓝风铃」歧义;版本(EDT/EDP/年份)不明时 edition=null,不得 confirmed。
- `identity_status`: 产品字典「存在核验」列为「官网已核验存在」→ "verified",否则 "待核验"。**产品存在核验 ≠ 仿香关系确认。**
- is_big_brand_dupe 本轮一律 null。

### 1.5 dupe_status
枚举:confirmed / strong_candidate / ambiguous / brand_only / unidentified / rejected。基线已按底稿设置;强产品线索=strong_candidate、歧义=ambiguous、仅品牌=brand_only、无线索=unidentified。本轮无 confirmed/rejected。

## 2. 输出契约(修正模式)

对批次中**每一行**输出一个 JSON 对象(一行一个,顺序与输入一致,行数必须相等),写入 `C:\Users\26519\Desktop\交付总控\ABC\_work\batches\batch_XXX_result.jsonl`。字段语义:**省略或 null = 保留基线**;add/remove 作用于基线。

```json
{
  "source_row": 3,
  "category_ids": null,
  "category_candidates": [],
  "tags_A1_add": [],
  "tags_A1_remove": [],
  "tags_A2_add": ["A2_e07e40863a"],
  "tags_A2_remove": [],
  "tags_A3_add": [],
  "tags_A3_remove": [],
  "tags_B_add": [],
  "tags_B_remove": [],
  "tags_C_add": {"CAT_07": ["C_980"]},
  "tags_C_remove": {},
  "product_candidates_add": [],
  "product_candidates_remove": [],
  "dupe_status": null,
  "unresolved_terms": [],
  "review_notes_add": [],
  "evidence_add": [{"tag_id": "A2_e07e40863a", "source_field": "名称", "source_text": "香柠檬", "inference_type": "semantic", "confidence": "medium"}],
  "status": null
}
```

约束:
- 所有 ID 必须存在于字典(dicts.txt / C.txt / products.txt);C 只输出该品类下的叶子。**不要输出 `A1_xxx` 这类占位符。**
- `product_candidates_add` 元素格式:`{"brand_id": "BR_001", "product_id": "PR_0001", "brand_name": "香奈儿", "product_name": "COCO Mademoiselle", "edition": null, "matched_alias": "COCO小姐", "identity_status": "待核验", "relation_status": "strong_candidate"}`;新产品:`{"brand_name": "...", "product_name": "...", "identity_status": "待核验", "relation_status": "candidate", "is_new_product": true}`。
- `inference_type` ∈ {legacy_mapping, name_inference, description, semantic, alias_mapping, product_clue};`confidence` ∈ {high, medium, low}。
- 若某行基线已完全正确,输出 `{"source_row": N}` 即可(极简)。
- 名称/上下文中的未识别气味术语放入 `unresolved_terms`(去重);不要发明 ID。

## 3. 输入字段说明

`input` 字段:source_row(原始行号)、fragrance_id(原编码字符串;"0"/空为待确认真实编号)、fragrance_name(原名称)、old_cat2/old_cat3/cat_remark(旧二级/三级/备注)、cat_id_screen/cat_screen(规则初筛品类)、a3_id_screen/a3_cn_screen(旧香族→A3 初筛)、entry_logic/is_new/is_hot(原标识,程序直抄)、dupe_status_screen、draft_product_candidates(程序产品候选底稿)、brand_only_hint、name_tag_hits(名称→AB 标签命中)、name_brand_hits/name_product_hits(名称→品牌/产品别名命中)、input_hash。

`baseline` 字段:程序预填的 category_ids、tags_A1/A2/A3/B、tags_C_by_category、dupe_status、product_candidates、tag_evidence、unresolved_terms、review_notes、status。

## 4. 执行步骤

1. 用 read 工具读取 dicts.txt(约65KB,一次读完)、C.txt、products.txt、batch.jsonl。
2. 逐行审查 baseline 并产出修正 JSON;注意 C 叶子的品类归属与叶子性。
3. 写入结果文件,行数与输入一致。
4. 完成后回复一行 JSON:`{"batch": "XXX", "rows": 30, "ok": true, "notes": "..."}`。

## 5. 少样本示范(baseline → 修正)

1) input: 蓝色琥珀(个人香氛,编码0), baseline: category=[CAT_01], A2=[A2_507b335ba9], B=[]:
`{"source_row": 2, "tags_B_add": ["B1_34ff19b8a8"], "evidence_add": [{"tag_id": "B1_34ff19b8a8", "source_field": "名称", "source_text": "蓝色", "inference_type": "semantic", "confidence": "low"}], "review_notes_add": ["编码0待核查;不推断具体配方"]}`

2) input: 香柠檬(织物护理 CAT_07, A3初筛=柑橘调), baseline: A1=[A1_5df314dc9f], A3=[A3_f7a4755450]:
`{"source_row": 3, "tags_A2_add": ["A2_e07e40863a"], "evidence_add": [{"tag_id": "A2_e07e40863a", "source_field": "名称", "source_text": "香柠檬", "inference_type": "semantic", "confidence": "medium"}]}`

3) input: 鲜茉莉(空间香氛 CAT_06, A3初筛=单一花香调), baseline: A1=[A1_578f5613cd], A3=[A3_bc383c2528]:
`{"source_row": 6, "tags_A2_add": ["A2_83fdd91606"], "tags_C_add": {"CAT_06": ["C_948"]}, "evidence_add": [{"tag_id": "A2_83fdd91606", "source_field": "名称", "source_text": "茉莉", "inference_type": "semantic", "confidence": "medium"}, {"tag_id": "C_948", "source_field": "品类+香型", "source_text": "空间香氛 花香", "inference_type": "semantic", "confidence": "medium"}]}`

4) input: COCO小姐(个人香氛 CAT_01, A3初筛=花香西普调), draft 产品 PR_0001(官网已核验), baseline: A3=[A3_f09e023ac1], product=[PR_0001], dupe=strong_candidate:
`{"source_row": 82, "tags_C_add": {"CAT_01": ["C_314"]}, "evidence_add": [{"tag_id": "C_314", "source_field": "品类+香型", "source_text": "个人香氛 花香西普", "inference_type": "semantic", "confidence": "medium"}], "review_notes_add": ["原香版本未确定;产品存在不代表仿香关系已确认"]}`

5) input: 黑鸦片洗衣液(织物护理 CAT_07, A3初筛=花香果香东方调), draft PR_0051(官网已核验), baseline: A3=[A3_9b65015838], product=[PR_0051], dupe=strong_candidate:
`{"source_row": 442, "tags_B_add": ["B5_dd6d753261"], "tags_C_add": {"CAT_07": ["C_980"]}, "evidence_add": [{"tag_id": "B5_dd6d753261", "source_field": "品类+语境", "source_text": "织物护理香水语境", "inference_type": "semantic", "confidence": "low"}, {"tag_id": "C_980", "source_field": "品类+语境", "source_text": "织物护理香水转化", "inference_type": "semantic", "confidence": "medium"}], "review_notes_add": ["有明确产品名+洗衣液语境;不编造咖啡等实际香韵"]}`

6) input: 香奈儿(织物护理 CAT_07, 无A3), baseline: category=[CAT_07], dupe=brand_only:
`{"source_row": 1322, "review_notes_add": ["仅品牌名不锁定产品;无香气描述不补AB"]}`

7) input: 鼠尾草与海盐(空间香氛 CAT_06, A3初筛=青绿木质调), draft PR_0023(歧义候选,官网已核验), baseline: A1=[A1_4e7d5ec8d2], A3=[A3_5a6fa7de4a], product=[PR_0023 ambiguous], dupe=ambiguous:
`{"source_row": 358, "tags_A2_add": ["A2_3ac920d779", "A2_5d71794f8c"], "tags_C_add": {"CAT_06": ["C_958", "C_952"]}, "evidence_add": [{"tag_id": "A2_3ac920d779", "source_field": "名称", "source_text": "海盐", "inference_type": "semantic", "confidence": "medium"}, {"tag_id": "A2_5d71794f8c", "source_field": "名称", "source_text": "鼠尾草", "inference_type": "semantic", "confidence": "medium"}, {"tag_id": "C_958", "source_field": "品类+香型", "source_text": "空间香氛 木质", "inference_type": "semantic", "confidence": "low"}, {"tag_id": "C_952", "source_field": "品类+香型", "source_text": "空间香氛 青绿", "inference_type": "semantic", "confidence": "low"}], "review_notes_add": ["名称可指气味也可指Jo Malone产品;仿香关系未确认"]}`

注意:示范中的 C ID(如 C_948/C_958/C_952/C_960/C_980/C_314 等)仅供示意,请务必对照你读取的 C.txt 核实叶子归属与品类后才输出。
