# 中央闻香库 第一轮冷启动 · 批次判定(v4 精简版)

你是标签判定员。程序已为每条记录生成基线(baseline,来自确定性规则)。你的任务:逐行审查基线并输出**修正**(补 A2/B/C、校验品类与 A1/A3、处理产品歧义、记录未识别术语),不要从头重写。冷启动试跑:候选覆盖优先于精确率,允许弱证据贴标;不强制填满;不制造无证据标签。

## 输入文件
- 字典: `C:\Users\26519\Desktop\交付总控\ABC\_work\ctx\slim\dicts.txt`(品类/A/B标签/品牌/C判定补充/旧转换)
- C 树(仅本批涉及品类的叶子): `C:\Users\26519\Desktop\交付总控\ABC\_work\ctx\slim\{bid}_C.txt`(id\t品类\t标签\t完整路径)
- 产品: `C:\Users\26519\Desktop\交付总控\ABC\_work\ctx\slim\{bid}_products.txt`
- 批次: `C:\Users\26519\Desktop\交付总控\ABC\_work\ctx\slim\{bid}_batch.jsonl`(每行 input+baseline,共30行)

## 判断规则
1. **品类**:基线来自规则初筛,保留。仅「其他家庭护理&清洁」「天然香养」等旧二级或空且基线为空时,按三级/备注判断;仍无法确认保持空并加 review_notes。`ALL` 不自动全贴。
2. **A1/A3**:基线来自名称命中/旧香族转换,保留;明显错误才 remove/add(仅限字典中存在且层级正确的 ID)。
3. **A2**:基线可能为空,由你判断:直接描述或有把握的 A1 语义(鲜茉莉→花香、柠檬→果香、檀香→木质)。只输出 tags_A.txt 中层级 A2 的 ID。不要把香水名解析成原料。
4. **B**:有把握才加:洗护/织物香水语境→B5_dd6d753261 香水感;「蓝色」→B1_34ff19b8a8(弱);描述词→对应 B。无把握留空。
5. **C**:只用 C 树中该品类的叶子。明确情形按 c_decision 补充(空间香氛茶香→茶香调;洗护/织物的香水转化叶;个人香氛的花香西普/花香调等)。无明确或合理弱语义支持就留空;不发明。产品形态不明的织物/身体洗护一般可不贴 C。
6. **产品身份**:基线候选一般保留。明显歧义(短词、普通香韵)改 relation_status=ambiguous;漏掉的强线索补 product_candidates_add(字典 product_id;没有的给候选名并 is_new_product=true);仅品牌名→dupe_status=brand_only 不加产品;「绿茶」≠雅顿绿茶;版本不明 edition=null。identity_status:产品字典「存在核验」=官网已核验存在→verified,否则待核验。is_big_brand_dupe 本轮一律 null。
7. **dupe_status**:confirmed/strong_candidate/ambiguous/brand_only/unidentified/rejected。强产品线索=strong_candidate,歧义=ambiguous,仅品牌=brand_only,无线索=unidentified。本轮无 confirmed/rejected。

## 输出契约(每输入行一行,写入 `C:\Users\26519\Desktop\交付总控\ABC\_work\batches\{bid}_result.jsonl`,行数与输入一致)
省略/null=保留基线;add/remove 作用于基线:
```json
{"source_row": 3, "category_ids": null, "category_candidates": [], "tags_A1_add": [], "tags_A1_remove": [],
 "tags_A2_add": ["A2_e07e40863a"], "tags_A2_remove": [], "tags_A3_add": [], "tags_A3_remove": [],
 "tags_B_add": [], "tags_B_remove": [], "tags_C_add": {"CAT_07": ["C_980"]}, "tags_C_remove": {},
 "product_candidates_add": [], "product_candidates_remove": [], "dupe_status": null,
 "unresolved_terms": [], "review_notes_add": [],
 "evidence_add": [{"tag_id": "A2_e07e40863a", "source_field": "名称", "source_text": "香柠檬", "inference_type": "semantic", "confidence": "medium"}],
 "status": null}
```
- product_candidates_add 元素:`{"brand_id": "BR_001", "product_id": "PR_0001", "brand_name": "香奈儿", "product_name": "COCO", "edition": null, "matched_alias": "COCO小姐", "identity_status": "待核验", "relation_status": "strong_candidate"}`;新产品加 `"is_new_product": true`。
- inference_type ∈ {legacy_mapping,name_inference,description,semantic,alias_mapping,product_clue};confidence ∈ {high,medium,low}。
- 基线已正确的行输出 `{"source_row": N}` 即可(极简)。未识别术语去重放入 unresolved_terms。

## 少样本
1. 蓝色琥珀(个人香氛,CAT_01):`{"source_row": 2, "tags_B_add": ["B1_34ff19b8a8"], "evidence_add": [{"tag_id": "B1_34ff19b8a8", "source_field": "名称", "source_text": "蓝色", "inference_type": "semantic", "confidence": "low"}], "review_notes_add": ["编码0待核查;不推断配方"]}`
2. 香柠檬(织物护理,CAT_07):`{"source_row": 3, "tags_A2_add": ["A2_e07e40863a"], "evidence_add": [{"tag_id": "A2_e07e40863a", "source_field": "名称", "source_text": "香柠檬", "inference_type": "semantic", "confidence": "medium"}]}`
3. 鲜茉莉(空间香氛,CAT_06):`{"source_row": 6, "tags_A2_add": ["A2_83fdd91606"], "tags_C_add": {"CAT_06": ["C_948"]}, "evidence_add": [{"tag_id": "A2_83fdd91606", "source_field": "名称", "source_text": "茉莉", "inference_type": "semantic", "confidence": "medium"}, {"tag_id": "C_948", "source_field": "品类+香型", "source_text": "空间香氛 花香", "inference_type": "semantic", "confidence": "medium"}]}`
4. COCO小姐(个人香氛,CAT_01,产品 PR_0001 已核验):`{"source_row": 82, "tags_C_add": {"CAT_01": ["C_314"]}, "evidence_add": [{"tag_id": "C_314", "source_field": "品类+香型", "source_text": "个人香氛 花香西普", "inference_type": "semantic", "confidence": "medium"}], "review_notes_add": ["原香版本未确定;产品存在≠仿香已确认"]}`
5. 黑鸦片洗衣液(织物护理,CAT_07):`{"source_row": 442, "tags_B_add": ["B5_dd6d753261"], "tags_C_add": {"CAT_07": ["C_980"]}, "evidence_add": [{"tag_id": "B5_dd6d753261", "source_field": "品类+语境", "source_text": "织物护理香水语境", "inference_type": "semantic", "confidence": "low"}, {"tag_id": "C_980", "source_field": "品类+语境", "source_text": "织物护理香水转化", "inference_type": "semantic", "confidence": "medium"}], "review_notes_add": ["不编造咖啡等实际香韵"]}`
6. 香奈儿(织物护理,无A3):`{"source_row": 1322, "review_notes_add": ["仅品牌名不锁定产品;无香气描述不补AB"]}`
7. 鼠尾草与海盐(空间香氛,CAT_06):`{"source_row": 358, "tags_A2_add": ["A2_3ac920d779", "A2_5d71794f8c"], "tags_C_add": {"CAT_06": ["C_958"]}, "evidence_add": [{"tag_id": "A2_3ac920d779", "source_field": "名称", "source_text": "海盐", "inference_type": "semantic", "confidence": "medium"}, {"tag_id": "A2_5d71794f8c", "source_field": "名称", "source_text": "鼠尾草", "inference_type": "semantic", "confidence": "medium"}, {"tag_id": "C_958", "source_field": "品类+香型", "source_text": "空间香氛 木质", "inference_type": "semantic", "confidence": "low"}], "review_notes_add": ["名称可指气味也可指Jo Malone产品;仿香未确认"]}`

注意:示范 C ID 仅供示意,务必对照你读取的 C 树核实叶子与品类。所有 ID 必须来自字典。
