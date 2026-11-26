from pathlib import Path

target = Path(__file__).resolve().parents[1] / "app" / "assets" / "rules.py"
text = target.read_text(encoding="utf-8")
marker = 'DUE_STAGE = {"R_IFRA": "before_release", "R_SDS": "before_supply", "Q_SPEC": "before_supply"}'
block = marker + '''

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
}'''
if "CATEGORY_ALIASES = {" in text:
    print("already present")
else:
    text = text.replace(marker, block, 1)
    target.write_text(text, encoding="utf-8")
    print("inserted")
