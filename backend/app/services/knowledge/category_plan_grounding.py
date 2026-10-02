"""Validate model category records against their exact source evidence."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas.knowledge_categories import CATEGORY_DOCUMENT_MODELS
from app.services.knowledge.category_contracts import validate_category_payload
from app.services.knowledge.category_markdown import _record_model
from app.services.knowledge.coercion import normalized_source_text
from app.project_knowledge.domain.category_catalog import get_category_definition


class CategoryPlanExtractionError(ValueError):
    """A safe failure receipt; never contains source text or provider output."""

    def __init__(self, message: str) -> None:
        messages = {
            "Saved category plan does not match the source": "Kết quả trích xuất không còn khớp với tệp đã lưu. Vui lòng nạp lại tệp.",
            "Source has no recruitment category facts": "Tệp chưa có thông tin tuyển dụng để điền danh mục. Vui lòng bổ sung thông tin dự án.",
            "Source exceeds the category extraction section budget": "Tệp vượt giới hạn xử lý danh mục. Hãy chia tệp thành các phần rồi thử lại.",
            "Extraction must account for every project category": "Kết quả phân loại chưa kiểm tra đủ 12 danh mục. Vui lòng thử lại.",
            "Category extraction is not a record list": "Kết quả phân loại danh mục chưa đúng định dạng. Vui lòng thử lại.",
            "Extraction checkpoint does not match the source": "Trạng thái xử lý đã lưu không khớp với tệp nguồn. Vui lòng nhập lại tệp.",
            "Extraction checkpoint has incomplete source coverage": "Trạng thái xử lý đã lưu thiếu phần nguồn. Vui lòng nhập lại tệp.",
            "Category extraction provider failed; retry the retained source": "Dịch vụ phân tích chưa hoàn tất. Vui lòng thử xử lý lại tệp đã lưu.",
            "Category extraction returned invalid JSON": "Dịch vụ phân tích trả về dữ liệu chưa hợp lệ. Vui lòng thử lại.",
            "Combined category extraction exceeds its valid schema or size": "Danh mục trích xuất vượt giới hạn hoặc chưa đúng định dạng. Hãy kiểm tra tệp rồi thử lại.",
            "Combined category plan exceeds the training size budget": "Nội dung danh mục trích xuất vượt giới hạn. Hãy chia tệp rồi thử lại.",
        }
        super().__init__(
            messages.get(
                message,
                "Có thông tin trích xuất chưa khớp với nguồn hoặc định dạng danh mục. Vui lòng kiểm tra tệp rồi thử lại.",
            )
        )


_NUMBER_RE = re.compile(
    r"(?<!\w)(\d+(?:[.,]\d+)*)(?:\s*(triệu|trieu|tr|nghìn|nghin|ngàn|ngan|million|thousand|k|m)(?!\w))?",
    re.IGNORECASE,
)
_ENUM_EVIDENCE = {
    "female": ("nữ",),
    "male": ("nam",),
    "any": (
        "nam và nữ",
        "nam nữ",
        "nam/nữ",
        "nam, nữ",
        "nam hoặc nữ",
        "mọi giới",
        "male and female",
        "all genders",
        "both genders",
    ),
    "hour": ("giờ",),
    "shift": ("ca",),
    "day": ("ngày",),
    "week": ("tuần",),
    "month": ("tháng",),
    "year": ("năm",),
    "one_time": (
        "một lần",
        "1 lần",
    ),
    "to_factory": ("đến nhà máy", "đi nhà máy", "đến công ty", "đi làm", "đưa đón"),
    "from_factory": (
        "từ nhà máy",
        "tan ca",
        "về nhà",
    ),
    "round_trip": (
        "hai chiều",
        "2 chiều",
        "đưa đón",
    ),
}


def _assertion_clauses(quote: str) -> list[str]:
    return [
        clause.strip()
        for clause in re.split(r"(?<=[.!?;])\s+|\b(?:nhưng|but)\b", quote, flags=re.IGNORECASE)
        if clause.strip() and not clause.strip().endswith("?")
    ]


def _has_free_assertion(quote: str) -> bool:
    for clause in _assertion_clauses(quote):
        if "không mất tiền" in clause.casefold():
            return True
        if re.search(r"\b(?:free|miễn phí)\b", clause, re.IGNORECASE) and not re.search(
            r"\b(?:không|not|no)\b", clause, re.IGNORECASE
        ):
            return True
    return False


def _source_numbers(quote: str, *, monetary: bool = False) -> set[int]:
    values: set[int] = set()
    currency = r"(?:vnd|vnđ|đồng|đ)(?!\w)"
    scales = r"(?:triệu|trieu|tr|nghìn|nghin|ngàn|ngan|million|thousand|k|m)"
    # Common Vietnamese shorthand: 6tr5 means 6.5 million, not 65 dong.
    for shorthand in re.finditer(r"(?<!\w)(\d+)tr(\d)(?!\w)", quote, re.IGNORECASE):
        values.add(int(shorthand[1]) * 1_000_000 + int(shorthand[2]) * 100_000)
    for match in _NUMBER_RE.finditer(quote):
        raw, unit = match.groups()
        # Shared-unit ranges: "8,5 - 10,5 triệu" also grounds the left bound.
        if not unit:
            suffix = quote[match.end() : match.end() + 40]
            shared = re.match(
                rf"\s*(?:[-–—]|đến|to)\s*\d+(?:[.,]\d+)*\s*({scales}|{currency})",
                suffix,
                re.IGNORECASE,
            )
            unit = shared.group(1) if shared else None
        before, after = (
            quote[max(0, match.start() - 12) : match.start()],
            quote[match.end() : match.end() + 12],
        )
        if monetary:
            if re.search(r"(?:usd|eur|\$|€)\s*$", before, re.IGNORECASE) or re.match(
                r"\s*(?:usd|eur|dollars|euros|\$|€)\b", after, re.IGNORECASE
            ):
                continue
            if not unit and not (
                re.search(rf"{currency}\s*$", before, re.IGNORECASE)
                or re.match(rf"\s*{currency}", after, re.IGNORECASE)
            ):
                continue
            if (
                unit
                and unit.lower() in {"million", "thousand", "m"}
                and not re.search(currency, quote, re.IGNORECASE)
            ):
                continue
        try:
            if not unit or re.fullmatch(currency, unit, re.IGNORECASE):
                if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+|\d+", raw):
                    values.add(int(re.sub(r"[.,]", "", raw)))
                else:
                    number = Decimal(raw.replace(",", "."))
                    if number == int(number):
                        values.add(int(number))
            else:
                number = Decimal(raw.replace(",", "."))
                factor = (
                    1_000_000 if unit.lower() in {"triệu", "trieu", "tr", "million", "m"} else 1000
                )
                scaled = number * factor
                if scaled == int(scaled):
                    values.add(int(scaled))
        except (ValueError, InvalidOperation):
            continue
    if _has_free_assertion(quote):
        values.add(0)
    return values


def _source_times(quote: str) -> set[str]:
    values = set()
    for match in re.finditer(
        r"(?<!\d)(\d{1,2})\s*(?::|giờ|hours?|h)(?![a-zA-Z])\s*(\d{1,2})?", quote, re.IGNORECASE
    ):
        hour, minute = int(match[1]), int(match[2] or 0)
        if hour < 24 and minute < 60:
            values.add(f"{hour:02}:{minute:02}")
    return values


def _resolve_schema(schema: dict[str, Any], definitions: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in schema:
        return definitions[schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def _validate_values(
    value: Any, schema: dict[str, Any], quote: str, definitions: dict[str, Any], field: str = ""
) -> None:
    schema = _resolve_schema(schema, definitions)
    if value is None:
        return
    if "anyOf" in schema:
        schema = next((item for item in schema["anyOf"] if item.get("type") != "null"), {})
        schema = _resolve_schema(schema, definitions)
    if isinstance(value, dict):
        for key, item in value.items():
            if key != "id":
                _validate_values(
                    item, schema.get("properties", {}).get(key, {}), quote, definitions, key
                )
    elif isinstance(value, list):
        for item in value:
            _validate_values(item, schema.get("items", {}), quote, definitions, field)
    elif isinstance(value, bool):
        if field == "crosses_midnight":
            return  # Computed from the two grounded shift times.
        # A denial of free housing/meals does not prove absence of the service.
        if field in {"available", "provided"}:
            service = (
                r"(?:ký túc xá|ktx|chỗ ở|nhà ở|housing|dormitor(?:y|ies)|accommodation|hostel)"
                if field == "available"
                else r"(?:bữa ăn|cơm ca|suất ăn|ăn ca|meals|meal service|meal)"
            )
            denial = re.search(
                rf"\bkhông\s+(?:(?:có|cung cấp|bố trí|phục vụ|hỗ trợ)\s+)?{service}(?!\s+(?:miễn phí|sáng|trưa|tối))"
                rf"|\bno\s+{service}(?!\s+(?:allowance|subsidy))"
                rf"|\b{service}\s+(?:(?:is|are)\s+)?not\s+(?:available|provided)",
                quote,
                re.IGNORECASE,
            )
            if bool(denial) == value or not re.search(service, quote, re.IGNORECASE):
                raise CategoryPlanExtractionError(
                    "Category record has an unsupported service denial"
                )
            if value:
                affirmed = False
                affirmative_service = (
                    f"(?:{service}|bữa\\s+(?:sáng|trưa|tối))" if field == "provided" else service
                )
                for clause in _assertion_clauses(quote):
                    clause = re.sub(r"không mất tiền", "miễn phí", clause, flags=re.IGNORECASE)
                    clause = re.sub(
                        r"không miễn phí|not free", "có phí", clause, flags=re.IGNORECASE
                    )
                    if re.search(
                        r"\b(?:không|not|no)\b|chưa rõ|chưa biết|unknown|unclear",
                        clause,
                        re.IGNORECASE,
                    ):
                        continue
                    if re.search(
                        rf"\b(?:có|cấp|cung cấp|phục vụ|bao|được|bố trí)\s+.{{0,40}}?{affirmative_service}"
                        rf"|{affirmative_service}\s*:?[ ]*(?:miễn phí|sẵn sàng|đang hoạt động|\d)"
                        rf"|{affirmative_service}\s+(?:(?:is|are)\s+)?(?:available|provided|free)"
                        rf"|\b(?:free|provided)\s+{affirmative_service}(?!\s+(?:allowance|subsidy))",
                        clause,
                        re.IGNORECASE,
                    ):
                        affirmed = True
                        break
                if not affirmed:
                    raise CategoryPlanExtractionError(
                        "Category record has no affirmative service evidence"
                    )
    elif isinstance(value, int):
        if field != "order" and value not in _source_numbers(
            quote, monetary=field.endswith("_vnd")
        ):
            raise CategoryPlanExtractionError("Category record contains an unsupported number")
    elif isinstance(value, str):
        folded_value = normalized_source_text(value).casefold()
        folded_quote = normalized_source_text(quote).casefold()
        if "enum" in schema:
            aliases = (value, *_ENUM_EVIDENCE.get(value, ()))
            if not any(
                re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", folded_quote) for alias in aliases
            ):
                raise CategoryPlanExtractionError("Category record contains an unsupported enum")
        elif field in {"phone", "zalo"} and re.fullmatch(r"[+\d\s().-]+", value):
            compact = re.sub(r"[\s().-]", "", folded_value)
            if compact not in re.sub(r"[\s().-]", "", folded_quote):
                raise CategoryPlanExtractionError(
                    "Category record contains an unsupported contact number"
                )
        elif field in {"time", "start_time", "end_time"}:
            if value not in _source_times(folded_quote):
                raise CategoryPlanExtractionError("Category record contains an unsupported time")
        elif folded_value and folded_value not in folded_quote:
            raise CategoryPlanExtractionError(
                "Category record contains text absent from its evidence"
            )


def validate_category_envelope(key: str, envelope: Any, source: str) -> dict[str, Any]:
    if not isinstance(envelope, dict) or set(envelope) != {"record", "source_quotes"}:
        raise CategoryPlanExtractionError("Category record has no evidence envelope")
    record, quotes = envelope["record"], envelope["source_quotes"]
    if not isinstance(record, dict) or not isinstance(quotes, list) or not quotes:
        raise CategoryPlanExtractionError("Category record has invalid evidence")
    folded_source = normalized_source_text(source)
    for quote in quotes:
        if (
            not isinstance(quote, str)
            or not normalized_source_text(quote)
            or normalized_source_text(quote) not in folded_source
        ):
            raise CategoryPlanExtractionError("Category record has no matching source quote")
    definition = get_category_definition(key)
    record_model = _record_model(CATEGORY_DOCUMENT_MODELS[definition.key], definition.list_field)
    fields = {field: value for field, value in record.items() if field != "id"}
    if not any(
        value is not None and value != "" and value != [] and value != {}
        for value in fields.values()
    ):
        raise CategoryPlanExtractionError("Category record contains no source facts")
    payload = {"category": key, key: [{"id": "pending", **fields}]}
    try:
        document = validate_category_payload(definition.key, payload)
    except ValueError:
        raise CategoryPlanExtractionError("Category record does not match its schema") from None
    validated_record = getattr(document, definition.list_field)[0].model_dump(mode="json")
    canonical_fields = {field: value for field, value in validated_record.items() if field != "id"}

    def normalized_facts(value):
        if isinstance(value, str):
            return normalized_source_text(value)
        if isinstance(value, list):
            return [normalized_facts(item) for item in value]
        if isinstance(value, dict):
            return {name: normalized_facts(item) for name, item in value.items()}
        return value

    stable = hashlib.sha256(
        json.dumps(normalized_facts(canonical_fields), ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:24]
    validated_record["id"] = f"auto-{key}-{stable}"
    schema = record_model.model_json_schema()
    _validate_values(
        fields, schema, normalized_source_text("\n".join(quotes)), schema.get("$defs", {})
    )
    # Explicit shift flags must agree with the grounded times.
    for shift in validated_record.get("shifts", []):
        if shift["crosses_midnight"] != (shift["end_time"] < shift["start_time"]):
            raise CategoryPlanExtractionError("Category shift has an inconsistent midnight flag")
    return {"record": validated_record, "source_quotes": quotes}
