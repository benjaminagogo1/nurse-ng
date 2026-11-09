"""Shared, bounded interest vocabulary for profiles and discovery."""

INTEREST_TERMS = {
    "Public health": ("public health", "epidemiology", "disease control"),
    "Digital health": ("digital health", "health informatics", "health technology"),
    "Community nursing": ("community", "primary health"),
    "Maternal health": ("maternal", "midwi", "reproductive health"),
    "Child health": ("paediatric", "pediatric", "child health", "neonatal"),
    "Critical care": ("critical care", "intensive care", "emergency"),
    "Mental health": ("mental health", "psychiatr"),
    "Research": ("research",),
    "Nursing education": ("educator", "tutor", "nursing education", "lecturer"),
    "Leadership": ("leadership", "manager", "management"),
    "Fellowships": ("fellow",),
    "Internships": ("intern", "graduate programme", "graduate program"),
}
INTEREST_OPTIONS = tuple(INTEREST_TERMS)
MAX_INTERESTS = 6


def interest_values(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def clean_interests(value: str) -> str:
    selected = set(interest_values(value))
    if not selected.issubset(INTEREST_OPTIONS):
        raise ValueError("Choose interests from the available options.")
    if len(selected) > MAX_INTERESTS:
        raise ValueError(f"Choose up to {MAX_INTERESTS} interests.")
    return ", ".join(item for item in INTEREST_OPTIONS if item in selected)
