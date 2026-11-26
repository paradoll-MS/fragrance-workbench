根据下面的判定表，为这个子项目在候选类型里选一个。

判定表：
1 有唯一可精确匹配的产品名 → find_product
2 客户已寄实物样，或要改已有样品 → with_sample
3 有内部编号或已发样，要改它 → modify
4 只有品牌/爆品/新品目录条件，没有唯一产品名 → recommend_simple
5 给定位/人群/场景/风格，没有具体产品 → recommend_brand
6 明确"没有参考/完全原创" → create
7 公司自己开新品线、没有客户 → invent
反例：要 N 款不同香型是系列选型，不是 create；提到法规/IFRA 不产生子项目；拿不准用 recommend_brand。

只输出 json：{"type":"","reason_code":"","confidence":0.0}
