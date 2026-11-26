"""Business vocabulary. Single source for codes and their Chinese labels."""

ENTRY_STRATEGIES = {
    "recommend_simple": ("select", "modify"),
    "recommend_brand": ("select", "create", "modify"),
    "find_product": ("select", "duplicate"),
    "with_sample": ("select", "duplicate", "create"),
    "modify": ("modify",),
    "invent": ("create",),
    "resend": ("resend",),
}
ENTRY_LABELS = {
    "recommend_simple": "常规推荐", "recommend_brand": "品牌推荐", "find_product": "精确找香",
    "with_sample": "对香", "modify": "改香", "invent": "主动开发", "resend": "复寄",
}
ENDPOINTS = {"shipment": "客户交付", "warehouse": "入库", "warehouse_return": "入库并回父项"}
ENDPOINT_LABELS = ENDPOINTS
ROUND_LABELS = {"initial": "首轮", "continue": "续轮", "resend": "复寄轮"}
SHIPMENT_LABELS = {"initial": "初寄样", "formal": "正式寄样", "resend": "复寄"}
TASK_TYPE_LABELS = {"analysis": "分析任务", "perfumery": "调香任务", "check": "检查任务",
                    "warehouse": "入库任务", "shipment": "寄样任务", "sample": "备样任务"}

MARKET_LABELS = {"CN": "中国大陆", "EU_EEA": "欧盟/欧洲经济区", "ASEAN": "东盟",
                 "US": "美国", "CA": "加拿大", "SA": "沙特", "AE": "阿联酋",
                 "GCC_OTHER": "海湾其他国家", "OTHER": "其他市场"}
MARKET_ALIASES = {
    "中国": "CN", "中国大陆": "CN", "国内": "CN", "china": "CN", "cn": "CN", "mainland": "CN",
    "欧盟": "EU_EEA", "欧洲": "EU_EEA", "eu": "EU_EEA", "europe": "EU_EEA", "欧": "EU_EEA",
    "东南亚": "ASEAN", "东盟": "ASEAN", "asean": "ASEAN",
    "美国": "US", "北美": "US", "us": "US", "usa": "US", "america": "US",
    "加拿大": "CA", "ca": "CA", "canada": "CA",
    "沙特": "SA", "sa": "SA", "saudi": "SA",
    "阿联酋": "AE", "迪拜": "AE", "ae": "AE", "uae": "AE",
    "海湾": "GCC_OTHER", "gcc": "GCC_OTHER", "中东": "GCC_OTHER",
    "其他": "OTHER", "other": "OTHER", "海外": "OTHER",
}
INTENTS = ("new", "continue", "modify", "resend")

STRATEGY_LABELS = {
    "select": "选定库香", "duplicate": "启动仿香", "create": "启动创香",
    "modify": "基于香精修改", "resend": "复寄原样", "adopt": "既有香替代",
}
STRATEGY_LABELS_SHORT = {
    "select": "选香", "duplicate": "仿香", "create": "创香", "modify": "改香",
    "resend": "复寄", "adopt": "替代",
}

STAGES = ("planned", "developing", "checking", "shipping", "complete", "cancelled")
STAGE_LABELS = {
    "planned": "待定方案", "developing": "开发中", "checking": "检查与放行",
    "shipping": "备样与寄样", "complete": "已完成", "cancelled": "已结束",
}

DEPARTMENTS = ("analysis", "perfumery", "compliance", "quality", "application", "warehouse", "sample", "shipment")
DEPARTMENT_LABELS = {
    "analysis": "分析", "perfumery": "调香", "compliance": "合规", "quality": "质量",
    "application": "应用", "warehouse": "入库", "sample": "备样", "shipment": "寄样",
}
CHECK_DEPARTMENTS = ("compliance", "quality", "application")

REQUIREMENT_STATUS = {
    "unverified": "待核销", "pending": "已派发", "passed": "已通过",
    "failed": "不符合", "not_applicable": "不适用", "needs_review": "待核对",
}
REQUIREMENT_SOURCES = {"default": "默认", "customer": "客户", "both": "客户与默认"}

RELEASE_ACTIONS = ("warehouse", "initial", "formal", "resend")
RELEASE_LABELS = {
    "warehouse": "入库放行", "initial": "初寄样放行", "formal": "正式寄样放行", "resend": "复寄放行",
}

PROJECT_KINDS = {"customer": "客户委托", "internal_upgrade": "内部升级", "invent": "主动开发"}

ISSUE_CODES = {
    "brief_incomplete": "需求待补",
    "reference_unresolved": "参照待确认",
    "formula_unknown": "配方未知",
    "sample_unavailable": "样品未到",
    "gc_pending": "等 GC 报告",
    "trial_pending": "等试作",
    "evaluation_pending": "等评香验收",
    "check_context_missing": "检查条件不足",
    "check_pending": "等检查回执",
    "check_failed": "存在不符合",
    "warehouse_pending": "等入库回执",
    "stock_short": "库存不足",
    "shipment_pending": "等寄样回执",
    "source_unreadable": "资料待补录",
    "blocked": "待人工处理",
}
RESUME_EVENTS = {
    "brief_incomplete": "brief_confirmed",
    "reference_unresolved": "reference_confirmed",
    "formula_unknown": "formula_ref_updated",
    "sample_unavailable": "sample_changed",
    "gc_pending": "task_result_accepted",
    "trial_pending": "task_result_accepted",
    "evaluation_pending": "evaluation_recorded",
    "check_context_missing": "brief_confirmed",
    "check_pending": "check_evidence_changed",
    "check_failed": "evaluation_recorded",
    "warehouse_pending": "task_result_accepted",
    "stock_short": "sample_available",
    "shipment_pending": "task_result_accepted",
    "source_unreadable": "source_added",
    "blocked": "manual_resolve",
}

TIERS = ("接近即可", "尽量一致", "自定义")
FULFILLMENT = {"ship": "客户交付", "warehouse": "内部入库"}
