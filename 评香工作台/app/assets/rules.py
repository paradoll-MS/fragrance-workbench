"""Review rules: turn the rule file into requirement drafts. No verdicts are computed here."""

import json

from .. import config
from ..domain import enums
from ..domain.models import CheckContext, RequirementDraft, conditions_fingerprint

# 条件默认项只有出现相应线索时才生成要求。触发词是规则文件 when 的可执行写法。
TRIGGERS = {
    "Q_FLASH": ("液体", "闪点", "运输", "危害"),
    "Q_COA": ("coa", "COA", "批次", "分析报告"),
    "R_ALLERGEN": ("过敏原", "过敏", "allergen"),
    "R_EXTRA": ("儿童", "宠物", "口腔", "食品接触", "清真", "认证", "限制", "宣称", "婴童"),
    "P9": ("摩擦", "复湿", "再释放", "运动"),
}
# 初次寄样可以暂缓的条目：法规与客户硬约束不可暂缓，其余可带说明暂缓。
DEFERRAL_BLOCKED = ("R_IFRA", "R_MARKET", "R_ALLERGEN", "R_EXTRA")
DUE_STAGE = {"R_IFRA": "before_release", "R_SDS": "before_supply", "Q_SPEC": "before_supply"}

# 基质与产品口语到审查品类的映射；只用于“猜”，猜不到就不填。
CATEGORY_ALIASES = {
    "洗发": "hair_rinse_off", "洗发水": "hair_rinse_off", "洗发露": "hair_rinse_off",
    "护发素": "hair_rinse_off", "发膜": "hair_rinse_off", "头皮": "hair_rinse_off",
    "护发": "hair_leave_on", "发油": "hair_leave_on", "发蜡": "hair_leave_on",
    "沐浴": "body_rinse_off", "沐浴露": "body_rinse_off", "洗手液": "body_rinse_off",
    "身体乳": "body_leave_on", "润肤": "body_leave_on", "身体": "body_leave_on",
    "洗面": "face_rinse_off", "洁面": "face_rinse_off",
    "面霜": "face_leave_on", "护肤": "face_leave_on", "精华": "face_leave_on", "面膜": "face_leave_on",
    "香水": "fine_fragrance", "香氛": "fine_fragrance", "淡香精": "fine_fragrance", "古龙": "fine_fragrance",
    "洗衣": "fabric_wash", "洗衣液": "fabric_wash", "洗涤": "fabric_wash",
    "柔顺": "fabric_deposition", "留香珠": "fabric_deposition", "织物": "fabric_deposition",
    "清洁剂": "hard_surface", "厨房": "hard_surface", "卫浴": "hard_surface", "硬表面": "hard_surface",
    "空气": "air_care", "除臭": "air_care", "香薰": "air_care",
    "蜡烛": "burning_diffusion", "线香": "burning_diffusion", "点燃": "burning_diffusion",
    "扩香": "passive_diffusion", "无火": "passive_diffusion", "藤条": "passive_diffusion",
    "牙膏": "oral_rinse_off", "漱口": "oral_rinse_off", "口腔": "oral_rinse_off",
    "唇膏": "lip_leave_on", "口红": "lip_leave_on", "唇": "lip_leave_on",
    "消毒": "disinfection_support", "杀菌": "disinfection_support",
    "除味": "malodor_control", "异味": "malodor_control",
}


class ReviewRules:
    def __init__(self, path=None):
        self.path = path or config.REVIEW_RULES
        data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        self.version = data["version"]
        self.status = data.get("status", "")
        self.metrics = data["metric_dictionary"]
        self.categories = data["review_category_defaults"]
        self.common = data["common_defaults"]
        self.conditional = data["conditional_defaults"]
        self.markets = data["market_defaults"]
        self.record_fields = data.get("record_fields", {})
        self.dispatch_rules = data.get("dispatch_rules", {})

    def category_options(self):
        return [{"id": key, "name": value["name"], "legal_identity_hint": value.get("legal_identity_hint", ""),
                 "context_note": value.get("context_note", ""), "stage_hints": value.get("stage_hints", [])}
                for key, value in self.categories.items()]

    def metric_options(self):
        return [{"id": key, "name": value["name"], "department": value["department"], "scope": value["scope"],
                 "record_hint": value.get("record_hint", "")} for key, value in self.metrics.items()]

    def infer_category(self, text):
        """按基质或最终产品文字猜审查品类；猜不到就留空，不硬套。"""
        text = (text or "").strip()
        if not text:
            return ""
        for word, key in CATEGORY_ALIASES.items():
            if word in text and key in self.categories:
                return key
        for key, value in self.categories.items():
            name = str(value.get("name", "")).rstrip("类")
            if name and (name in text or text in name):
                return key
        return ""

    def department(self, metric_id):
        return self.metrics.get(metric_id, {}).get("department", "compliance")

    def criterion(self, metric_id, subitem):
        name = self.metrics.get(metric_id, {}).get("name", metric_id)
        hint = self.metrics.get(metric_id, {}).get("record_hint", "")
        return f"{name}{('/' + subitem) if subitem else ''}：{hint}" if hint else name

    def _draft(self, metric_id, subitem="", source="default", source_key="default", mandatory=True,
               origin_text="", conditions=None, due_stage=""):
        if metric_id not in self.metrics:
            return None
        return RequirementDraft(
            metric_id=metric_id,
            subitem=subitem,
            department=self.department(metric_id),
            source=source,
            source_key=source_key,
            criteria=self.criterion(metric_id, subitem),
            mandatory=mandatory,
            deferral="blocked" if metric_id in DEFERRAL_BLOCKED else "allowed",
            due_stage=due_stage or DUE_STAGE.get(metric_id, "before_release"),
            origin_text=origin_text,
            conditions=conditions or {},
        )

    def build(self, context: CheckContext):
        """Return (requirements, coverage) for one fragrance version and one scope."""
        drafts, coverage = {}, []
        category = self.categories.get(context.review_category)
        if not category:
            coverage.append({"code": "review_category_missing",
                             "text": "审查品类未确认，只生成通用与客户要求"})
        else:
            for item in category.get("defaults", []):
                metric_id, subitem = item.get("metric_id"), item.get("subitem", "")
                activation = item.get("activation", "") or category["name"] + "默认要求"
                key = f"default:{metric_id}:{subitem}"
                draft = self._draft(metric_id, subitem, source_key=key, mandatory=not item.get("activation"),
                                    origin_text=activation, conditions={"review_category": context.review_category})
                if draft:
                    drafts.setdefault((metric_id, subitem), draft)
            coverage.append({"code": "review_category", "text": category["name"],
                             "note": category.get("context_note", "")})

        for item in self.common:
            metric_id = item["metric_id"]
            key = f"default:{metric_id}:"
            draft = self._draft(metric_id, source_key=key, mandatory=metric_id == "R_IFRA",
                                origin_text=item.get("activation", "") or "通用默认要求",
                                due_stage=item.get("stage", ""))
            if draft:
                drafts.setdefault((metric_id, ""), draft)

        haystack = " ".join(filter(None, [
            " ".join(requirement.get("text", "") for requirement in context.customer_requirements),
            context.substrate, context.dose_text, context.end_product,
        ]))
        for item in self.conditional:
            metric_id, subitem = item["metric_id"], item.get("subitem", "")
            triggers = TRIGGERS.get(metric_id, ())
            if not any(trigger.casefold() in haystack.casefold() for trigger in triggers):
                continue
            draft = self._draft(metric_id, subitem, source_key=f"conditional:{metric_id}:{subitem}",
                                mandatory=False, origin_text=item.get("when", ""))
            if draft:
                drafts.setdefault((metric_id, subitem), draft)

        for market in context.markets:
            single = self.markets.get(market)
            if not single:
                coverage.append({"code": "market_unknown", "text": f"市场 {market} 无默认规则，待确认"})
                continue
            draft = self._draft("R_MARKET", subitem=single["name"], source_key=f"market:{market}",
                                mandatory=True, origin_text=single.get("default", "") or market + " 市场要求",
                                conditions={"market": market})
            if draft:
                drafts.setdefault(("R_MARKET", single["name"]), draft)
            for hint in single.get("review_hints", []):
                coverage.append({"code": "market_route", "market": market, "route": hint.get("route", ""),
                                 "if": hint.get("if", ""), "note": hint.get("note", ""),
                                 "sources": hint.get("source_urls", [])})

        for requirement in context.customer_requirements:
            text = str(requirement.get("text", "")).strip()
            if not text:
                continue
            metric_id = str(requirement.get("metric_id") or "R_EXTRA")
            subitem = str(requirement.get("subitem") or text[:80])
            key = f"customer:{text[:60]}"
            draft = self._draft(metric_id, subitem=subitem, source="customer", source_key=key,
                                mandatory=bool(requirement.get("mandatory", True)), origin_text=text)
            if draft:
                drafts[(f"customer:{key}", metric_id)] = draft
            elif metric_id != "R_EXTRA":
                fallback = self._draft("R_EXTRA", subitem=text[:80], source="customer", source_key=key,
                                       mandatory=bool(requirement.get("mandatory", True)), origin_text=text)
                if fallback:
                    drafts[(f"customer:{key}", "")] = fallback

        if not context.markets:
            coverage.append({"code": "market_missing", "text": "目标市场未确认，销售地法规待定"})
        if not context.review_category:
            coverage.append({"code": "dosage_missing", "text": "实际用量/基质未确认，应用与法规条件待定"})

        ordered = sorted(drafts.values(), key=lambda draft: (
            enums.CHECK_DEPARTMENTS.index(draft.department) if draft.department in enums.CHECK_DEPARTMENTS else 9,
            draft.metric_id, draft.subitem))
        return ordered, coverage


def group_by_department(requirements):
    groups = {}
    for requirement in requirements:
        groups.setdefault(requirement.department, []).append(requirement)
    return groups


def condition_key(conditions):
    return conditions_fingerprint(conditions)
