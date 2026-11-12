"""Salary facts from explicitly labelled remuneration, without guessing currency or period."""

import re
from decimal import Decimal

LABEL = re.compile(
    r"^(?:(?:gross|net|monthly|annual|hourly|daily|weekly|yearly)\s+){0,2}"
    r"(?:salary(?:\s+(?:range|offered|package))?|remuneration|compensation|pay(?:\s+range)?)"
    r"\s*(?::\s*(.*)|$)", re.I,
)
CURRENCY = r"(?:NGN|USD|GBP|EUR|CAD|AUD|ZAR|KES|GHS|Naira|US\$|₦|£|€)"
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?(?:[ \t]*[kKmM]\b)?"
AMOUNT = re.compile(
    rf"(?P<currency>{CURRENCY})\s*(?P<low>{NUMBER})"
    rf"(?:\s*(?:[-–—]|\bto\b)\s*(?P<second>{CURRENCY})?\s*(?P<high>{NUMBER}))?"
    r"(?![\d,.])",
    re.I,
)
UNITS = {
    "HOUR": r"\b(?:hourly|per\s+hour|an?\s+hour)\b|/\s*(?:hour|hr)\b",
    "DAY": r"\b(?:daily|per\s+day|a\s+day)\b|/\s*day\b",
    "WEEK": r"\b(?:weekly|per\s+week|a\s+week)\b|/\s*week\b",
    "MONTH": r"\b(?:monthly|per\s+month|a\s+month)\b|/\s*(?:month|mo)\b",
    "YEAR": r"\b(?:annual|annually|yearly|per\s+(?:year|annum)|a\s+year)\b"
            r"|/\s*year\b",
}
OTHER_SECTION = re.compile(
    r"^(?:[A-Za-z][A-Za-z &'()/,-]{1,55}\s*[:–—]|"
    r"(?:benefits?|requirements?|qualifications?|responsibilities|application|"
    r"how to apply|location|transport|relocation|bonus|allowances?)\b)", re.I,
)


def currency_code(value):
    return {"₦": "NGN", "NAIRA": "NGN", "£": "GBP", "€": "EUR", "US$": "USD"}.get(
        value.upper(), value.upper()
    )


def _number(value):
    value = value.replace(",", "").replace(" ", "")
    multiplier = {"k": 1000, "m": 1000000}.get(value[-1:].lower(), 1)
    amount = Decimal(value[:-1] if multiplier != 1 else value) * multiplier
    return str(amount)


def salary_from_text(text: str) -> dict:
    """Read a short labelled block; conflicting salary statements remain unresolved."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    salaries = []
    for index, line in enumerate(lines):
        if not LABEL.match(line):
            continue
        # A label and its value can be split across paragraphs, table cells or newlines.
        block_lines = [line]
        for following in lines[index + 1:index + 4]:
            if LABEL.match(following) or OTHER_SECTION.match(following):
                break
            block_lines.append(following)
        block = " ".join(block_lines)[:240]
        if re.search(r"\b(?:expected|expectation|previous|current salary|desired)\b", block, re.I):
            continue
        amounts = list(AMOUNT.finditer(block))
        if len(amounts) != 1:
            continue
        amount = amounts[0]
        # An adjacent fee, bonus or benefit is not evidence of base salary, even inline.
        if re.search(r"\b(?:fees?|allowances?|bonus|bonuses)\b", block[:amount.start()], re.I):
            continue
        if re.search(r"[-−]\s*$", block[:amount.start()]):
            continue
        currency = currency_code(amount['currency'])
        if amount['second'] and currency_code(amount['second']) != currency:
            continue
        units = [unit for unit, pattern in UNITS.items() if re.search(pattern, block, re.I)]
        if len(units) > 1:
            continue
        salary = {"currency": currency, "unit": units[0] if units else ""}
        if amount['high']:
            salary.update(minValue=_number(amount['low']), maxValue=_number(amount['high']))
        else:
            qualifier = block[:amount.start()]
            key = "maxValue" if re.search(r"\bup to\b", qualifier, re.I) else (
                "minValue" if re.search(r"\b(?:from|starting at|minimum)\b", qualifier, re.I)
                else "value"
            )
            salary[key] = _number(amount['low'])
        bases = {word.lower() for word in re.findall(r"\b(gross|net)\b", block, re.I)}
        if len(bases) == 1:
            salary["basis"] = bases.pop()
        if salary not in salaries:
            salaries.append(salary)
    return salaries[0] if len(salaries) == 1 else {}
