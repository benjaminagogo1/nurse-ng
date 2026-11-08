"""Shared relevance rules for health jobs and Nigerian early-career opportunities."""

import re

NURSING = re.compile(r"\b(nurs(?:e|es|ing)|midwi(?:fe|ves|fery)|RN)\b", re.I)
HEALTH_FIELD = re.compile(
    r"\b(?:(?:public|community|primary|digital|global|mental|maternal|national)[ -]+health|"
    r"health(?:care|[ -]+(?:care|informatics|information|data|systems?|fellow\w*))|"
    r"clinical|medical|epidemiolog\w*)\b", re.I,
)
EARLY_CAREER = re.compile(
    r"\b(?:fellows?(?:hip)?s?|interns?(?:hip)?s?|graduate|trainees?|apprentice\w*)\b", re.I,
)


def relevant_opportunity(data: dict) -> bool:
    """Recognize relevance, never infer an applicant's qualifications or eligibility.

    Nigerian early-career programmes may span sectors, such as Jubilee Fellows.
    International trainee titles need an explicit health field in their description.
    An employer's name alone cannot make an unrelated vacancy relevant.
    """
    title = data.get("title", "")
    return bool(
        NURSING.search(title)
        or HEALTH_FIELD.search(title)
        or (data.get("country") == "NG" and EARLY_CAREER.search(title))
        or (EARLY_CAREER.search(title) and HEALTH_FIELD.search(data.get("description", "")))
    )


def programme_type(title: str) -> str:
    if re.search(r"\bfellows?(?:hip)?s?\b", title, re.I):
        return "fellowship"
    if re.search(r"\binterns?(?:hip)?s?\b", title, re.I):
        return "internship"
    if re.search(
        r"\b(?:graduate[ -]+(?:trainees?|programmes?|programs?)|traineeship)\b", title, re.I,
    ):
        return "graduate_programme"
    return ""
