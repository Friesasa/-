from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib import request

from .field_mapping import STANDARD_FIELDS


INQUIRY_FIELDS = [
    "nickname",
    "contact_status",
    "available_date",
    "schedule_531",
    "rebate_ratio",
    "free_distribution",
    "infoflow_auth_6m",
    "discount_order",
    "self_invest",
    "cooperation_notes",
    "deliverables",
    "image_price",
    "video_price",
    "region",
]


def parse_inquiry_text(text: str, brand_headers: list[str] | None = None) -> dict[str, Any]:
    if os.getenv("OPENAI_API_KEY"):
        try:
            return _ensure_standalone_nickname(_parse_with_openai(text, brand_headers or []), text)
        except Exception as exc:
            fallback = _parse_with_rules(text)
            fallback["warnings"].append(f"LLM 调用失败，已使用本地规则解析：{exc}")
            return _ensure_standalone_nickname(fallback, text)
    fallback = _parse_with_rules(text)
    fallback["warnings"].append("未配置 OPENAI_API_KEY，当前使用本地关键词规则解析。")
    return _ensure_standalone_nickname(fallback, text)


def _parse_with_openai(text: str, brand_headers: list[str]) -> dict[str, Any]:
    api_key = os.environ["OPENAI_API_KEY"]
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    labels = {field: STANDARD_FIELDS[field]["label"] for field in INQUIRY_FIELDS}
    prompt = {
        "task": "从小红书达人二询反馈文本中提取字段。只返回 JSON。",
        "standard_fields": labels,
        "brand_headers": brand_headers,
        "rules": [
            "没有明确出现的信息不要编造，放入 missing_fields。",
            "fields 只放有把握的信息。",
            "evidence 写对应原文片段。",
            "confidence 使用 0 到 1。",
            "如果第一行或最后一行是单独出现的达人昵称，即使没有“达人名/昵称”标签，也提取为 nickname。",
        ],
        "text": text,
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是媒介表格信息抽取助手，擅长把达人二询文字转成结构化 JSON。"},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    req = request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with request.urlopen(req, timeout=45) as response:
        data = json.loads(response.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return _normalize_llm_result(parsed)


def _normalize_llm_result(parsed: dict[str, Any]) -> dict[str, Any]:
    raw_fields = parsed.get("fields") or {}
    fields = {}
    for key, value in raw_fields.items():
        if key not in STANDARD_FIELDS:
            continue
        normalized_value = _normalize_extracted_value(value)
        if normalized_value in (None, ""):
            continue
        fields[key] = normalized_value
    missing = parsed.get("missing_fields") or parsed.get("missing") or []
    if isinstance(missing, dict):
        missing = list(missing)
    return {
        "fields": fields,
        "missing_fields": missing,
        "evidence": parsed.get("evidence", {}),
        "confidence": parsed.get("confidence", {}),
        "warnings": parsed.get("warnings", []),
        "raw": parsed,
    }


def _normalize_extracted_value(value: Any) -> Any:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, str) and value.strip().lower() in {"missing", "未提及", "无", "none", "null", "n/a"}:
        return None
    return value


def _ensure_standalone_nickname(result: dict[str, Any], text: str) -> dict[str, Any]:
    fields = result.setdefault("fields", {})
    if fields.get("nickname"):
        return result
    nickname = _standalone_nickname_candidate(text)
    if not nickname:
        return result
    fields["nickname"] = nickname
    result.setdefault("evidence", {})["nickname"] = nickname
    result.setdefault("confidence", {})["nickname"] = 0.75
    missing = result.get("missing_fields")
    if isinstance(missing, list):
        result["missing_fields"] = [field for field in missing if field != "nickname"]
    return result


def _standalone_nickname_candidate(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in [*lines[:2], *reversed(lines[-2:])]:
        if _looks_like_standalone_nickname(line):
            return line
    return None


def _looks_like_standalone_nickname(line: str) -> bool:
    if line.startswith("#") or re.search(r"[:：]", line):
        return False
    if len(line) > 30:
        return False
    if re.search(r"(项目|平台|报价|返点|档期|授权|分发|薯条|是否|可以|小红书)", line):
        return False
    return bool(re.search(r"[\w\u4e00-\u9fff]", line))


def _parse_with_rules(text: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    evidence: dict[str, str] = {}
    clean = text.strip()
    if re.search(r"可接|可以接|能接|有档期|可合作", clean):
        fields["contact_status"] = "可接"
        evidence["contact_status"] = _first_match(clean, r".{0,8}(可接|可以接|能接|有档期|可合作).{0,8}")
    elif re.search(r"不接|暂不|没档期|无档期|拒", clean):
        fields["contact_status"] = "暂不接"
        evidence["contact_status"] = _first_match(clean, r".{0,8}(不接|暂不|没档期|无档期|拒).{0,8}")
    date_match = re.search(r"(\d{1,2}[月./-]\d{1,2}[日号]?|本周|下周|月底|月初|[一二三四五六七八九十]+月[一二三四五六七八九十\d]+[日号]?)", clean)
    if date_match:
        fields["available_date"] = date_match.group(1)
        evidence["available_date"] = date_match.group(0)
    nickname = _value_after_label(clean, ["达人名", "达人昵称", "昵称"])
    if nickname:
        fields["nickname"] = nickname
        evidence["nickname"] = nickname
    schedule_531 = _value_after_label(clean, ["5.31档期是否OK", "发布档期531是否可以", "531是否可以", "发布档期530是否可以"])
    if schedule_531:
        fields["schedule_531"] = schedule_531
        evidence["schedule_531"] = schedule_531
    rebate = _value_after_label(clean, ["返点比例", "返点比例（30%以上）", "返点"])
    if rebate:
        fields["rebate_ratio"] = rebate
        evidence["rebate_ratio"] = rebate
    free_distribution = _value_after_label(clean, ["1-可否免费分发其他平台（具体哪个）", "可否免费分发其他平台", "免费分发其他平台"])
    if free_distribution:
        fields["free_distribution"] = free_distribution
        evidence["free_distribution"] = free_distribution
    auth = _value_after_label(clean, ["3-免费授权信息流6个月", "免费授权信息流6个月"])
    if auth:
        fields["infoflow_auth_6m"] = auth
        evidence["infoflow_auth_6m"] = auth
    discount = _value_after_label(clean, ["4：需要改价8折接单，剩下的线下返", "需要改价8折接单", "8折接单"])
    if discount:
        fields["discount_order"] = discount
        evidence["discount_order"] = discount
    invest = _value_after_label(clean, ["5：能不能自己投报价的10%费用薯条（或能自行投多少写出具体金额）", "5：可否自行投薯条裸价的10%（或能自行投多少写出具体金额）", "能不能自己投报价的10%费用薯条", "可否自行投蒲公英裸价的10%", "自行投薯条", "能自行投多少"])
    if invest:
        fields["self_invest"] = invest
        evidence["self_invest"] = invest
    image_price = _price_after(clean, ["图文", "单图", "图"])
    if image_price:
        fields["image_price"] = image_price
        evidence["image_price"] = image_price
    video_price = _price_after(clean, ["视频"])
    if video_price:
        fields["video_price"] = video_price
        evidence["video_price"] = video_price
    if re.search(r"图文|视频|合集|报备|非报备|探店|种草", clean):
        fields["deliverables"] = "；".join(sorted(set(re.findall(r"图文|视频|合集|报备|非报备|探店|种草", clean))))
        evidence["deliverables"] = fields["deliverables"]
    fields["cooperation_notes"] = clean
    evidence["cooperation_notes"] = clean[:120]
    missing = [field for field in INQUIRY_FIELDS if field not in fields]
    return {
        "fields": fields,
        "missing_fields": missing,
        "evidence": evidence,
        "confidence": {field: 0.65 for field in fields},
        "warnings": [],
    }


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(0) if match else ""


def _price_after(text: str, markers: list[str]) -> str | None:
    for marker in markers:
        pattern = rf"{marker}.{{0,8}}?(\d+(?:\.\d+)?\s*[w万k千元块]?)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return re.sub(r"\s+", "", match.group(1))
    return None


def _value_after_label(text: str, labels: list[str]) -> str | None:
    for label in labels:
        pattern = rf"{re.escape(label)}\s*(?:[（(][^）)]*[）)])?\s*[:：]\s*([^\n\r]+)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip().strip("\t :：")
            return value or None
        pattern = rf"{re.escape(label)}\s*[:：]?\s*([^\n\r]+)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip().strip("\t :：")
            return _strip_inline_prompt_note(value) or None
    return None


def _strip_inline_prompt_note(value: str) -> str:
    match = re.match(r"^[（(][^）)]*[）)]\s*[:：]\s*(.+)$", value)
    if match:
        return match.group(1).strip()
    return value

