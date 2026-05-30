from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


STANDARD_FIELDS: dict[str, dict[str, Any]] = {
    "nickname": {"label": "昵称", "aliases": ["昵称", "达人昵称", "博主昵称", "账号名称", "达人"]},
    "account_id": {"label": "小红书号", "aliases": ["小红书号", "账号ID", "账号id", "达人ID", "达人id", "小红书ID", "id", "ID"]},
    "blogger_id": {"label": "博主ID", "aliases": ["博主ID", "博主id", "蒲公英ID", "蒲公英id"]},
    "homepage": {"label": "主页链接", "aliases": ["主页链接", "小红书主页", "账号链接", "达人主页", "链接"]},
    "pgy_url": {"label": "蒲公英链接", "aliases": ["蒲公英链接", "蒲公英主页", "蒲公英"]},
    "account_type": {"label": "账号类型", "aliases": ["账号类型", "达人类型", "博主类型", "内容类型", "类目"]},
    "followers_w": {"label": "粉丝量/w", "aliases": ["粉丝量/w", "粉丝数（万）", "粉丝量", "粉丝数", "粉丝"]},
    "exposure_median": {"label": "曝光中位数", "aliases": ["曝光中位数", "曝光", "预估曝光"]},
    "read_median": {"label": "阅读中位数", "aliases": ["阅读中位数", "阅读", "浏览", "浏览量"]},
    "engagement_median": {"label": "互动中位数", "aliases": ["互动中位数", "互动", "互动量"]},
    "image_price": {"label": "图文报价", "aliases": ["图文报价", "图文笔记一口价", "图文价格", "图文费用"]},
    "video_price": {"label": "视频报价", "aliases": ["视频报价", "视频笔记一口价", "视频价格", "视频费用"]},
    "image_cpm": {"label": "图文CPM", "aliases": ["图文预估cpm", "图文cpm", "图文CPM"]},
    "video_cpm": {"label": "视频CPM", "aliases": ["视频预估cpm", "视频cpm", "视频CPM"]},
    "image_cpe": {"label": "图文CPE", "aliases": ["图文预估cpe", "图文cpe", "图文CPE"]},
    "video_cpe": {"label": "视频CPE", "aliases": ["视频预估cpe", "视频cpe", "视频CPE"]},
    "female_ratio": {"label": "女性粉丝", "aliases": ["女性粉丝", "女粉占比", "女性占比", "女粉"]},
    "male_ratio": {"label": "男性粉丝", "aliases": ["男性粉丝", "男粉占比", "男性占比", "男粉"]},
    "adult_ratio": {"label": ">18占比", "aliases": [">18占比", "18岁以上", "成年粉丝", "18+占比"]},
    "region": {"label": "地区", "aliases": ["地区", "城市", "所在地", "地域", "地理位置"]},
    "tags": {"label": "内容标签", "aliases": ["内容标签", "标签", "内容方向", "擅长领域"]},
    "organization": {"label": "机构", "aliases": ["机构", "MCN", "mcn", "所属机构"]},
    "contact_status": {"label": "二询状态", "aliases": ["二询状态", "档期状态", "合作状态", "是否可接"]},
    "available_date": {"label": "可合作档期", "aliases": ["档期", "可合作档期", "可发布时间", "发布时间", "排期"]},
    "schedule_531": {"label": "5.31档期是否OK", "aliases": ["5.31档期是否OK", "531是否可以", "531档期", "发布档期531是否可以", "5.31是否可以"]},
    "rebate_ratio": {"label": "返点比例", "aliases": ["返点比例", "返点", "返点比例（30%以上）", "返佣比例"]},
    "free_distribution": {"label": "免费分发其他平台", "aliases": ["可否免费分发其他平台", "免费分发其他平台", "其他平台分发", "分发平台"]},
    "infoflow_auth_6m": {"label": "免费授权信息流6个月", "aliases": ["免费授权信息流6个月", "信息流授权", "授权信息流", "免费授权"]},
    "discount_order": {"label": "8折改价接单", "aliases": ["需要改价8折接单", "8折接单", "改价8折", "剩下的线下返"]},
    "self_invest": {"label": "自行投薯条", "aliases": ["可否自行投蒲公英裸价的10%", "自行投薯条", "自行投报价的10%费用薯条", "能自行投多少", "薯条"]},
    "cooperation_notes": {"label": "二询备注", "aliases": ["二询备注", "达人反馈", "反馈", "备注", "特殊要求"]},
    "deliverables": {"label": "合作形式", "aliases": ["合作形式", "产出形式", "笔记形式", "需求形式"]},
}


def normalize_header(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value)).strip().lower()


def match_standard_field(header: Any) -> tuple[str | None, float]:
    normalized = normalize_header(header)
    if not normalized:
        return None, 0
    best_field = None
    best_score = 0.0
    for field, info in STANDARD_FIELDS.items():
        if field == "nickname" and any(token in normalized for token in ("id", "链接", "主页", "蒲公英", "视频号", "分发")):
            continue
        candidates = [info["label"], *info["aliases"]]
        for candidate in candidates:
            alias = normalize_header(candidate)
            if normalized == alias:
                return field, 1.0
            if alias and (alias in normalized or normalized in alias):
                score = min(len(alias), len(normalized)) / max(len(alias), len(normalized))
                score = max(score, 0.82)
            else:
                score = SequenceMatcher(None, normalized, alias).ratio()
            if score > best_score:
                best_field = field
                best_score = score
    if best_score < 0.58:
        return None, best_score
    return best_field, round(best_score, 2)


def standard_label(field: str | None) -> str:
    if not field:
        return ""
    return STANDARD_FIELDS.get(field, {}).get("label", field)


def empty(value: Any) -> bool:
    return value is None or str(value).strip() == ""

