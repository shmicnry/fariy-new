"""Explicit speaker/subject frames for a small, verifiable personal-memory question class."""

import re


def infer_subject(quote):
    text = re.sub(
        r"^(?:请(?:帮我)?记住|帮我记住|记住|请记下|记下)[：:,，\s]*", "", quote.strip()
    )
    return "owner" if re.match(r"^(?:我|本人|用户)", text) else "unspecified"


def normalized_fact(quote, subject):
    text = re.sub(
        r"^(?:请(?:帮我)?记住|帮我记住|记住|请记下|记下)[：:,，\s]*", "", quote.strip()
    )
    labels = {
        "owner": "用户",
        "assistant": "助手",
        "other": "其他人物",
        "unspecified": "主体待明确",
    }
    if subject == "owner" and re.match(r"^(?:我|本人|用户)", text):
        return re.sub(r"^(?:本人|用户|我)", "用户", text)
    return (
        labels.get(subject, "主体待明确") + "的已确认陈述（原文引用）：“" + quote + "”"
    )


def personal_question(text):
    # Only this explicit question shape is grounded by this rule. Other intents stay with the model.
    match = re.fullmatch(
        r"(?:请问[，,\s]*)?(我|你)(?:现在|平时|日常|一般|最)?喜欢喝(?:什么|啥|哪种饮料|哪种饮品|哪种茶)[？?。\s]*(.*)",
        text.strip(),
    )
    if not match:
        return None
    suffix = match.group(2).strip()
    if suffix and not re.match(
        r"^(?:只根据|只用|如果没有|没有记录|请直接|别猜|不要猜|请根据|请只)", suffix
    ):
        return None
    return "owner" if match.group(1) == "我" else "assistant"


def ground_personal_answer(context):
    subject = context.get("query_subject")
    if context.get("intent") != "personal_drink_preference":
        return None
    if subject == "assistant":
        return {
            "reply": "我没有真实的饮品偏好。你的个人偏好与 Fairy 的角色设定是分开记录的。",
            "basis": "assistant_identity",
            "memory_ids": [],
        }
    facts = [
        e
        for e in context["entries"]
        if e.get("kind") == "quoted_memory"
        and e.get("subject") == "owner"
        and re.search(r"(?:喜欢|偏好|爱|只)(?:喝|饮用)", e.get("quote", ""))
    ]
    if not facts:
        return {
            "reply": "目前没有可用的、已确认的你的饮品偏好记录，所以我不知道你喜欢喝什么。",
            "basis": "no_confirmed_memory",
            "memory_ids": [],
        }
    statements = [
        e["statement"].replace("用户", "你", 1).rstrip("。.!！") for e in facts
    ]
    reply = (
        "根据你已确认的记忆，" + statements[0] + "。"
        if len(statements) == 1
        else "你已确认的相关记忆有：\n" + "\n".join("- " + t for t in statements)
    )
    return {
        "reply": reply,
        "basis": "confirmed_memory",
        "memory_ids": [e["id"] for e in facts],
    }
