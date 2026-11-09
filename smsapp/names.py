"""Student-name helpers: parsing typed names, composing the full name and the register display form."""
import re


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def parse_name(text: str) -> tuple[str, str, str]:
    """'Mensah, John Kwame' or 'John Kwame Mensah' -> (first, middle, surname). One word is treated as a first name."""
    text = _clean(text)
    if not text:
        return "", "", ""
    if "," in text:
        sur, _, rest = text.partition(",")
        parts = _clean(rest).split(" ") if _clean(rest) else []
        return (parts[0] if parts else ""), " ".join(parts[1:]), _clean(sur)
    parts = text.split(" ")
    if len(parts) == 1:
        return parts[0], "", ""
    return parts[0], " ".join(parts[1:-1]), parts[-1]


def compose(first: str, middle: str, surname: str) -> str:
    return _clean(" ".join(x for x in (first, middle, surname) if _clean(x)))


def register_name(first: str, middle: str, surname: str) -> str:
    """'Surname, First Middle' as printed on class registers."""
    rest = _clean(f"{first} {middle}")
    sur = _clean(surname)
    return f"{sur}, {rest}" if sur and rest else (sur or rest)


def next_student_id(db_scalar) -> str:
    """STD00001, STD00002, ... the next number after the highest one in use."""
    n = db_scalar("SELECT COALESCE(MAX(CAST(SUBSTR(admission_no, 4) AS INTEGER)), 0) FROM students "
                  "WHERE admission_no GLOB 'STD[0-9]*' AND admission_no NOT GLOB 'STD*[^0-9]*'", default=0)
    return f"STD{int(n) + 1:05d}"
