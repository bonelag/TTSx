"""TTSx Vietnamese text pipeline & phonemizer — Python thuần.

Pipeline xử lý văn bản tiếng Việt cho TTSx Studio:
  - Chuẩn hóa văn bản: emoji/dấu câu, số/ngày tháng/giờ/tiền tệ -> chữ,
    viết tắt + từ điển 17.711 từ ngoại lai, phiên âm English -> Việt, lowercase
  - Tách câu theo [.!?] (không tách dấu phẩy — giữ nhịp trong câu)
  - Phonemize espeak-ng IPA (qua espeakng-loader) + merge separator
  - Tone digit restoration: chèn digit thanh điệu cho âm tiết thanh ngang
    (espeak-ng mới bỏ digit này, nhưng model được train với digit đầy đủ 1-7)

Quy luật tone digit (phân tích thực nghiệm):
  - Thanh ngang thường  -> digit "1", chèn SAU nguyên âm, TRƯỚC phụ âm cuối
    (sˈiɲ -> sˈi1ɲ, hˈaːj -> hˈaː1j, ɗˈi -> ɗˈi1)
  - Thanh ngang mang stress chính (ˈ) cuối cùng của mệnh đề -> digit "7"
  - Các thanh khác espeak-ng vẫn giữ: huyền=2, ngã/hỏi=4, nặng=6, sắc=marker "ɜ"
"""

import ctypes
import csv
import re
import unicodedata
from pathlib import Path
from typing import List, Optional

_DATA_DIR = Path(__file__).resolve().parent / "ttsx_data"

# ---------------------------------------------------------------------------
# 1. Vietnamese word detection (port vietnamese-detector.js)
# ---------------------------------------------------------------------------

_VN_ACCENT_RE = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]",
    re.IGNORECASE,
)
_EN_SPECIAL_RE = re.compile(r"[fwzj]", re.IGNORECASE)
_VN_ONSETS = {
    "b", "c", "d", "đ", "g", "h", "k", "l", "m", "n", "p", "q", "r", "s", "t", "v", "x",
    "ch", "gh", "gi", "kh", "ng", "nh", "ph", "qu", "th", "tr",
}
_VN_ENDINGS = {"p", "t", "c", "m", "n", "ng", "ch", "nh"}
_CVC_RE = re.compile(r"^([^ueoaiy]*)([ueoaiy]+)([^ueoaiy]*)$")


def is_vietnamese_word(word: str) -> bool:
    if not word:
        return False
    w = word.lower().strip()
    if _VN_ACCENT_RE.search(w):
        return True
    if _EN_SPECIAL_RE.search(w):
        return False
    m = _CVC_RE.match(w)
    if not m:
        return False
    onset, vowel, ending = m.group(1), m.group(2), m.group(3)
    if onset and onset not in _VN_ONSETS:
        return False
    if ending and ending not in _VN_ENDINGS:
        return False
    if re.search(r"ee|oo|ea|oa|ae|ie", vowel):
        if vowel not in ("oa", "oe", "ua", "uy"):
            return False
    return True


# ---------------------------------------------------------------------------
# 2. English -> Vietnamese transliteration (port transliterator.js)
# ---------------------------------------------------------------------------

# (pattern, replacement) — giữ đúng thứ tự của bản JS
_HP_RULES = [
    (r"tion$", "ân"), (r"sion$", "ân"), (r"age$", "ây"), (r"ing$", "ing"),
    (r"ture$", "chờ"), (r"cial$", "xô"), (r"tial$", "xô"),
    (r"aught", "ót"), (r"ought", "ót"), (r"ound", "ao"), (r"ight", "ai"),
    (r"eigh", "ây"), (r"ough", "ao"),
    (r"\bst(?!r)", "t"), (r"\bstr", "tr"), (r"\bsch", "c"), (r"\bsc(?=h)", "c"),
    (r"\bsc|sk", "c"), (r"\bsp", "p"), (r"\btr", "tr"), (r"\bbr", "r"),
    (r"\bcr|pr|gr|dr|fr", "r"), (r"\bbl|cl|sl|pl", "l"), (r"\bfl", "ph"),
    (r"ck", "c"), (r"sh", "s"), (r"ch", "ch"), (r"th", "th"), (r"ph", "ph"),
    (r"wh", "q"), (r"qu", "q"), (r"kn", "n"), (r"wr", "r"),
]

_END_RULES = [
    (r"le$", "ồ"),
    (r"ook$", "úc"), (r"ood$", "út"), (r"ool$", "un"), (r"oom$", "um"), (r"oon$", "un"),
    (r"oot$", "út"), (r"iend$", "en"), (r"end$", "en"), (r"eau$", "iu"),
    (r"ail$", "ain"), (r"ain$", "ain"), (r"ait$", "ât"),
    (r"oat$", "ốt"), (r"oad$", "ốt"), (r"oal$", "ôn"),
    (r"eep$", "íp"), (r"eet$", "ít"), (r"eel$", "in"),
    (r"atch$", "át"), (r"etch$", "éch"), (r"itch$", "ích"), (r"otch$", "ốt"), (r"utch$", "út"),
    (r"edge$", "ét"), (r"idge$", "ít"), (r"odge$", "ót"), (r"udge$", "út"),
    (r"ack$", "ác"), (r"eck$", "éc"), (r"ick$", "ích"), (r"ock$", "óc"), (r"uck$", "úc"),
    (r"ash$", "át"), (r"esh$", "ét"), (r"ish$", "ít"), (r"osh$", "ốt"), (r"ush$", "út"),
    (r"ath$", "át"), (r"eth$", "ét"), (r"ith$", "ít"), (r"oth$", "ót"), (r"uth$", "út"),
    (r"ate$", "ây"), (r"ete$", "ét"), (r"ite$", "ai"), (r"ote$", "ốt"), (r"ute$", "út"),
    (r"ade$", "ây"), (r"ede$", "ét"), (r"ide$", "ai"), (r"ode$", "ốt"), (r"ude$", "út"),
    (r"ake$", "ây"), (r"ame$", "am"), (r"ane$", "an"), (r"ape$", "ếp"), (r"eke$", "ét"),
    (r"eme$", "êm"), (r"ene$", "en"), (r"ike$", "íc"), (r"ime$", "am"), (r"ine$", "ai"),
    (r"oke$", "ốc"), (r"ome$", "om"), (r"one$", "oăn"), (r"uke$", "ấc"), (r"ume$", "uym"),
    (r"une$", "uyn"),
    (r"ase$", "ây"), (r"ise$", "ai"), (r"ose$", "âu"),
    (r"all$", "âu"), (r"ell$", "eo"), (r"ill$", "iu"), (r"oll$", "ôn"), (r"ull$", "un"),
    (r"ang$", "ang"), (r"eng$", "ing"), (r"ong$", "ong"), (r"ung$", "âng"),
    (r"air$", "e"), (r"ear$", "ia"), (r"ire$", "ai"), (r"ure$", "iu"), (r"our$", "ao"),
    (r"ore$", "o"), (r"ound$", "ao"), (r"ight$", "ai"), (r"aught$", "ót"),
    (r"ought$", "ót"), (r"eigh$", "ây"), (r"ork$", "ót"),
    (r"ee$", "i"), (r"ea$", "i"), (r"oo$", "u"), (r"oa$", "oa"), (r"oe$", "oe"),
    (r"ai$", "ai"), (r"ay$", "ay"), (r"au$", "au"), (r"aw$", "â"), (r"ei$", "ây"),
    (r"ey$", "ây"), (r"oi$", "oi"), (r"oy$", "oi"), (r"ou$", "u"), (r"ow$", "ô"),
    (r"ue$", "ue"), (r"ui$", "ui"), (r"ie$", "ai"), (r"eu$", "iu"),
    (r"ar$", "a"), (r"er$", "ơ"), (r"ir$", "ơ"), (r"or$", "o"), (r"ur$", "ơ"),
    (r"al$", "an"), (r"el$", "eo"), (r"il$", "iu"), (r"ol$", "ôn"), (r"ul$", "un"),
    (r"ab$", "áp"), (r"ad$", "át"), (r"ag$", "ác"), (r"ak$", "át"), (r"ap$", "áp"),
    (r"at$", "át"), (r"eb$", "ép"), (r"ed$", "ét"), (r"eg$", "ét"), (r"ek$", "éc"),
    (r"ep$", "ép"), (r"et$", "ét"), (r"ib$", "íp"), (r"id$", "ít"), (r"ig$", "íc"),
    (r"ik$", "íc"), (r"ip$", "íp"), (r"it$", "ít"), (r"ob$", "óp"), (r"od$", "ót"),
    (r"og$", "óc"), (r"ok$", "óc"), (r"op$", "óp"), (r"ot$", "ót"), (r"ub$", "úp"),
    (r"ud$", "út"), (r"ug$", "úc"), (r"uk$", "úc"), (r"up$", "úp"), (r"ut$", "út"),
    (r"am$", "am"), (r"an$", "an"), (r"em$", "em"), (r"en$", "en"), (r"im$", "im"),
    (r"in$", "in"), (r"om$", "om"), (r"on$", "on"), (r"um$", "âm"), (r"un$", "ân"),
    (r"as$", "ẹt"), (r"es$", "ẹt"), (r"is$", "ít"), (r"os$", "ọt"), (r"us$", "ợt"),
    (r"aa$", "a"), (r"ii$", "i"), (r"uu$", "u"),
]

_GEN_RULES = [
    (r"j", "d"), (r"z", "d"), (r"w", "u"), (r"x", "x"), (r"v", "v"), (r"f", "ph"),
    (r"s", "x"), (r"c", "k"), (r"q", "ku"),
    (r"a", "a"), (r"e", "e"), (r"i", "i"), (r"o", "o"), (r"u", "u"),
]

_VOWELS = "aeiouăâêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
_Syll_RE = re.compile(rf"[^{_VOWELS}]*[{_VOWELS}]+[ptcmngs]?(?![{_VOWELS}])")
_VALID_PAIRS = {"ch", "th", "ph", "sh", "ng", "tr", "nh", "gh", "kh"}
_CONSONANTS = "bcdfghjklmnpqrstvwxz"


def _apply_rules(w: str, rules) -> str:
    for pattern, repl in rules:
        w = re.sub(pattern, repl, w)
    return w


def _clean_syllable(p: str) -> str:
    if not p:
        return ""
    # Xóa phụ âm kép không hợp lệ (bb, rr, ...)
    p = re.sub(r"([brlptdgmnckxsvfzjwqh])\1+", r"\1", p)
    # Giữ cụm phụ âm hợp lệ, ngược lại bỏ ký tự đầu
    result = ""
    i = 0
    while i < len(p):
        if i < len(p) - 1 and p[i] in _CONSONANTS and p[i + 1] in _CONSONANTS:
            pair = p[i] + p[i + 1]
            if pair in _VALID_PAIRS:
                result += pair
                i += 2
            else:
                result += p[i + 1]
                i += 2
        else:
            result += p[i]
            i += 1
    p = result
    # Quy tắc C/K
    if not p.startswith(("ch", "th", "ph", "sh")):
        if p.startswith(("k", "c")):
            nxt = p[1:2]
            p = ("k" if nxt in ("i", "e", "y") else "c") + p[1:]
    # Lọc phụ âm cuối hợp lệ
    if len(p) > 1 and p[-1] not in _VOWELS:
        last = p[-1]
        if last not in ("p", "t", "c", "m", "n", "g", "s"):
            p = p[:-1] + "n" if last == "l" else p[:-1]
    return p


def _english_to_vietnamese(word: str) -> str:
    w = word.lower().strip()
    if not w:
        return ""
    if w.startswith("y"):
        w = "d" + w[1:]
    if w.startswith("d"):
        w = "đ" + w[1:]

    w = _apply_rules(w, _HP_RULES)
    w = _apply_rules(w, _END_RULES)
    w = _apply_rules(w, _GEN_RULES)
    w = re.sub(r"([bcdfghjklmnpqrstvwxz])y", r"\1i", w)
    w = re.sub(r"y$", "i", w)

    parts = _Syll_RE.findall(w)
    if not parts:
        return w

    finals = []
    for syl in parts:
        s = syl.strip()
        if not s:
            continue
        if s.startswith("y"):
            s = "d" + s[1:]
        s = _apply_rules(s, _HP_RULES)
        s = _apply_rules(s, _END_RULES)
        s = _apply_rules(s, _GEN_RULES)
        s = re.sub(r"([bcdfghjklmnpqrstvwxz])y", r"\1i", s)
        s = re.sub(r"y$", "i", s)
        finals.append(s)

    finals = [_clean_syllable(p) for p in finals]
    finals = [p for p in finals if p]
    return "-".join(finals)


def transliterate_word(word: str) -> str:
    if not word:
        return word or ""
    if is_vietnamese_word(word):
        return word
    return _english_to_vietnamese(word)


# ---------------------------------------------------------------------------
# 3. Number / date / currency -> chữ
# ---------------------------------------------------------------------------

_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
_MONTHS = ["giêng", "hai", "ba", "tư", "năm", "sáu", "bảy", "tám", "chín", "mười", "mười một", "chạp"]

_DIGIT_WORDS = {"0": "không", "1": "một", "2": "hai", "3": "ba", "4": "bốn",
                "5": "năm", "6": "sáu", "7": "bảy", "8": "tám", "9": "chín"}
_TEENS = {"10": "mười", "11": "mười một", "12": "mười hai", "13": "mười ba",
          "14": "mười bốn", "15": "mười lăm", "16": "mười sáu", "17": "mười bảy",
          "18": "mười tám", "19": "mười chín"}
_TENS = {"2": "hai mươi", "3": "ba mươi", "4": "bốn mươi", "5": "năm mươi",
         "6": "sáu mươi", "7": "bảy mươi", "8": "tám mươi", "9": "chín mươi"}


def _three_digits_to_words(n: int) -> str:
    parts = []
    trăm = n // 100
    if trăm > 0:
        parts.append(_DIGITS[trăm])
        parts.append("trăm")
    chục = (n % 100) // 10
    đơn = n % 10
    if chục > 0:
        parts.append("mười" if chục == 1 else _DIGITS[chục] + " mươi")
        if đơn == 5:
            parts.append("lăm")
        elif đơn > 0:
            parts.append("một" if đơn == 1 else _DIGITS[đơn])
    elif đơn > 0:
        if trăm > 0:
            parts.append("lẻ")
        parts.append(_DIGITS[đơn])
    return " ".join(parts)


def _number_to_words(num_str: str) -> str:
    """Đọc số tiếng Việt chuẩn (mốt/tư/lăm, 'không trăm' cho nhóm <100)."""
    num_str = num_str.replace(".", "").replace(",", "")
    num_str = num_str.lstrip("0") or "0"
    if num_str.startswith("-"):
        return "âm " + _number_to_words(num_str[1:])
    n = int(num_str)
    if n == 0:
        return "không"
    if n < 10:
        return _DIGIT_WORDS[str(n)]
    if n < 20:
        return _TEENS[str(n)]
    if n < 100:
        tens, units = divmod(n, 10)
        if units == 0:
            return _TENS[str(tens)]
        if units == 1:
            return _TENS[str(tens)] + " mốt"
        if units == 4:
            return _TENS[str(tens)] + " tư"
        if units == 5:
            return _TENS[str(tens)] + " lăm"
        return _TENS[str(tens)] + " " + _DIGIT_WORDS[str(units)]
    if n < 1000:
        hundreds, remainder = divmod(n, 100)
        result = _DIGIT_WORDS[str(hundreds)] + " trăm"
        if remainder == 0:
            return result
        if remainder < 10:
            return result + " lẻ " + _DIGIT_WORDS[str(remainder)]
        return result + " " + _number_to_words(str(remainder))

    scales = [(10**9, "tỷ"), (10**6, "triệu"), (10**3, "nghìn")]
    for value, name in scales:
        if n >= value:
            head, remainder = divmod(n, value)
            result = _number_to_words(str(head)) + " " + name
            if remainder == 0:
                return result
            if remainder < 100:
                if remainder < 10:
                    return result + " không trăm lẻ " + _DIGIT_WORDS[str(remainder)]
                return result + " không trăm " + _number_to_words(str(remainder))
            return result + " " + _number_to_words(str(remainder))
    # Số cực lớn: đọc từng chữ số
    return " ".join(_DIGIT_WORDS.get(d, d) for d in num_str)


_DATE_FULL_RE = re.compile(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})")
_SINH_NGAY_RE = re.compile(r"(sinh\s+)(ngày\s+)(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", re.IGNORECASE)
_DAY_MONTH_RE = re.compile(r"\bngày\s+(\d{1,2})[/\-.](\d{1,2})\b", re.IGNORECASE)
_DECIMAL_RE = re.compile(r"(\d+),(\d+)")  # thập phân chỉ dùng dấu phẩy; dấu chấm = ngăn cách nghìn
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)*)\s*%")
_CURRENCY_RE = re.compile(r"(\d+(?:[.,]\d+)*)\s*(đồng|vnd|usd|đ|đ\.|\$)", re.IGNORECASE)
_TIME_HM_RE = re.compile(r"\b(\d{1,2})h(\d{2})\b")
_TIME_H_RE = re.compile(r"\b(\d{1,2})h\b")
_TIME_GIO_RE = re.compile(r"(\d+)\s*giờ\s*(\d+)\s*phút")


def process_vietnamese_text(text: str) -> str:
    # "Sinh ngày dd/mm/yyyy" -> không lặp "ngày"
    def _sinh_repl(m):
        d, mth, y = m.group(3), m.group(4), m.group(5)
        return f"{m.group(1)}ngày {_number_to_words(d)} tháng {_number_to_words(mth)} năm {_number_to_words(y)}"

    text = _SINH_NGAY_RE.sub(_sinh_repl, text)

    # dd/mm/yyyy -> "ngày D tháng M năm Y" (giữ nguyên "ngày" đứng trước nếu có —
    # giữ nguyên từ đứng trước nếu có)
    def _date_repl(m):
        d, mth, y = m.group(1), m.group(2), m.group(3)
        if not (1 <= int(d) <= 31 and 1 <= int(mth) <= 12):
            return m.group(0)
        return f"ngày {_number_to_words(d)} tháng {_number_to_words(mth)} năm {_number_to_words(y)}"

    text = _DATE_FULL_RE.sub(_date_repl, text)

    def _dm_repl(m):
        d, mth = m.group(1), m.group(2)
        mi = int(mth)
        if not (1 <= int(d) <= 31 and 1 <= mi <= 12):
            return m.group(0)
        month_word = _MONTHS[mi - 1]
        return f"ngày {_number_to_words(d)} tháng {month_word}"

    text = _DAY_MONTH_RE.sub(_dm_repl, text)

    # Thời gian: 15h30 -> mười lăm giờ ba mươi; 9h -> chín giờ; 2 giờ 20 phút
    text = _TIME_GIO_RE.sub(
        lambda m: f"{_number_to_words(m.group(1))} giờ {_number_to_words(m.group(2))} phút", text
    )
    text = _TIME_HM_RE.sub(
        lambda m: f"{_number_to_words(m.group(1))} giờ {_number_to_words(m.group(2))}", text
    )
    text = _TIME_H_RE.sub(lambda m: f"{_number_to_words(m.group(1))} giờ", text)

    text = _PERCENT_RE.sub(lambda m: m.group(1) + " phần trăm", text)
    text = _CURRENCY_RE.sub(lambda m: m.group(1) + " đồng", text)

    def _dec_repl(m):
        return _number_to_words(m.group(1)) + " phẩy " + _number_to_words(m.group(2))

    text = _DECIMAL_RE.sub(_dec_repl, text)
    text = _NUM_RE.sub(lambda m: _number_to_words(m.group(0)), text)
    return text


# ---------------------------------------------------------------------------
# 4. Text cleaning + CSV từ điển (port text-cleaner.js)
# ---------------------------------------------------------------------------

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF☀-⛿✀-➿\U0001F900-\U0001F9FF"
    "\U0001F018-\U0001F270⎌-⑔⃐-⃿️‍"
    "]", re.UNICODE
)

_acronym_map_cache = None
_word_map_cache = None


def _load_csv_map(filename: str, key_col: str):
    """Đọc CSV (header row: key_col -> value cột cuối) thành dict lowercase->value."""
    path = _DATA_DIR / filename
    result = {}
    if not path.exists():
        return result
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if key_col in row and row[key_col]:
                value = row.get("transliteration") or row.get("meaning") or list(row.values())[-1]
                if value:
                    result[row[key_col].strip().lower()] = value.strip()
    return result


def _get_acronym_map():
    global _acronym_map_cache
    if _acronym_map_cache is None:
        _acronym_map_cache = _load_csv_map("acronyms.csv", "acronym")
    return _acronym_map_cache


def _get_word_map():
    global _word_map_cache
    if _word_map_cache is None:
        _word_map_cache = _load_csv_map("non-vietnamese-words.csv", "original")
    return _word_map_cache


def clean_text_for_tts(text: str) -> str:
    if not text:
        return ""
    cleaned = _EMOJI_RE.sub("", text)
    cleaned = re.sub(r"[\\()¯]", "", cleaned)
    cleaned = re.sub(r"[“”„\"]", "", cleaned)
    cleaned = re.sub(r"\s—", ".", cleaned)
    cleaned = re.sub(r"\b_\b", " ", cleaned)
    cleaned = re.sub(r"(?<!\d)-(?!\d)", " ", cleaned)
    cleaned = re.sub(r"[^\u0000-\u024FḀ-ỿ]", "", cleaned)
    return cleaned.strip()


_TRANSLIT_SKIP = {"mc"}
_WORD_RE = re.compile(r"(?:^|[^\wÀ-ỿ])([\wÀ-ỿ]+)(?=[^\wÀ-ỿ]|$)")


def _apply_transliteration(text: str, replacement_map: dict) -> str:
    result = text
    processed = set()
    for m in _WORD_RE.finditer(text):
        word = m.group(1)
        wl = word.lower()
        if wl in processed:
            continue
        processed.add(wl)
        if wl in replacement_map:
            continue
        if is_vietnamese_word(word) or is_vietnamese_word(wl):
            continue
        if len(word) == 1 or wl in _TRANSLIT_SKIP:
            continue
        translit = transliterate_word(word)
        if translit == word:
            continue
        escaped = re.escape(word)
        not_word = r"[^\wÀ-ỿ]"
        pattern = re.compile(rf"(?:^|({not_word}))({escaped})(?={not_word}|$)", re.IGNORECASE)

        def _repl(mm, _t=translit):
            w_part = mm.group(2)
            if w_part and w_part[0] == w_part[0].upper():
                return (mm.group(1) or "") + _t[0].upper() + _t[1:]
            return (mm.group(1) or "") + _t

        result = pattern.sub(_repl, result)
    return result


def process_text_for_tts(text: str) -> str:
    """Text thô -> text đã clean + số->chữ + viết tắt + phiên âm + lowercase."""
    if not text:
        return ""
    cleaned = clean_text_for_tts(text)
    processed = process_vietnamese_text(cleaned)
    lowered = processed.lower()

    # Acronym conversion
    acronyms = _get_acronym_map()
    for acr, repl in acronyms.items():
        lowered = re.sub(rf"\b{re.escape(acr)}\b", repl, lowered, flags=re.IGNORECASE)

    # Non-Vietnamese words từ CSV (ưu tiên trước transliteration)
    word_map = _get_word_map()
    for orig, repl in word_map.items():
        lowered = re.sub(rf"\b{re.escape(orig)}\b", repl, lowered, flags=re.IGNORECASE)

    # Transliteration cho từ còn lại
    lowered = _apply_transliteration(lowered, word_map)
    return lowered


# ---------------------------------------------------------------------------
# 5. Chunking — tách câu
# ---------------------------------------------------------------------------


def split_sentences(text: str) -> List[str]:
    chunks: List[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if not re.search(r"[.!?]$", line):
            line = line + "."
        for sentence in re.split(r"(?<=[.!?])(?=\s+|$)", line):
            sentence = sentence.strip()
            if sentence:
                chunks.append(sentence)
    return chunks


# ---------------------------------------------------------------------------
# 6. espeak-ng phonemizer (ctypes + espeakng-loader)
# ---------------------------------------------------------------------------

_ESPEAK_LIB = None
_ESPEAK_VOICE = None


def _get_espeak_lib():
    global _ESPEAK_LIB
    if _ESPEAK_LIB is not None:
        return _ESPEAK_LIB
    import espeakng_loader

    lib = ctypes.CDLL(espeakng_loader.get_library_path())
    lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    lib.espeak_Initialize(1, 0, espeakng_loader.get_data_path().encode(), 0)
    lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
    lib.espeak_TextToPhonemes.restype = ctypes.c_char_p
    lib.espeak_TextToPhonemes.argtypes = [ctypes.POINTER(ctypes.c_char_p), ctypes.c_int, ctypes.c_int]
    _ESPEAK_LIB = lib
    return lib


def _espeak_set_voice(voice: str):
    global _ESPEAK_VOICE
    if _ESPEAK_VOICE == voice:
        return
    lib = _get_espeak_lib()
    lib.espeak_SetVoiceByName(voice.encode("utf-8"))
    _ESPEAK_VOICE = voice


def espeak_phonemize_clause(clause: str) -> str:
    """Phonemize MỘT mệnh đề bằng espeak-ng IPA."""
    lib = _get_espeak_lib()
    text = ctypes.c_char_p(clause.encode("utf-8"))
    out = lib.espeak_TextToPhonemes(ctypes.byref(text), 0, 0x02)  # 0x02 = IPA
    return out.decode("utf-8") if out else ""


# ---------------------------------------------------------------------------
# 7. Tone digit restoration
# ---------------------------------------------------------------------------

_CODA_CONSONANTS = set("mnɲŋptkjwʔ")
_DIGIT_RE = re.compile(r"[1-7]")


def _insert_tone_digit(core: str, digit: str) -> str:
    """Chèn digit sau nguyên âm cuối — trước TOÀN BỘ phụ âm cuối (nếu có)."""
    j = len(core)
    while j > 0:
        k = j
        while k > 0 and unicodedata.combining(core[k - 1]) != 0:
            k -= 1
        if k == 0:
            break
        base = core[k - 1]
        if base in _VOWEL_CHARS or base in "ːˑʰʲʷ-" or base.isdigit() or base in _STRESS_CHARS:
            break
        j = k - 1
    return core[:j] + digit + core[j:]


_VOWEL_CHARS = set("aeiouyəɛɔɑæɒʌøɵʉɯɪʊɜ")
_STRESS_CHARS = "ˈˌ"


def _split_syllables(core: str) -> List[str]:
    """Tách token phoneme thành các âm tiết.

    Mỗi stress mark (ˈ/ˌ) sau cái đầu tiên bắt đầu một âm tiết mới:
      - Nếu ngay trước có >= 2 phụ âm: phụ âm gần nhất là onset của âm tiết mới
        (phần còn lại là coda của âm tiết trước).
      - Nếu có <= 1 phụ âm: phụ âm đó (nếu có) là coda của âm tiết trước,
        âm tiết mới bắt đầu ngay tại stress mark.
    """
    splits = []
    first_stress_seen = False
    for i, ch in enumerate(core):
        if ch not in _STRESS_CHARS:
            continue
        if not first_stress_seen:
            first_stress_seen = True
            continue  # stress đầu: không tạo ranh giới
        if i == 0:
            continue
        # Đếm các consonant unit liền trước stress mark
        j = i
        unit_starts = []
        while j > 0:
            k = j
            while k > 0 and unicodedata.combining(core[k - 1]) != 0:
                k -= 1
            if k == 0:
                break
            base = core[k - 1]
            if base in _VOWEL_CHARS or base.isdigit() or base in _STRESS_CHARS:
                break
            unit_starts.append(k - 1)
            j = k - 1
        if len(unit_starts) >= 2:
            splits.append(unit_starts[0])  # onset của âm tiết mới
        else:
            splits.append(i)
        first_stress_seen = True

    if not splits:
        return [core]
    parts = []
    prev = 0
    for s in splits:
        if s > prev:
            parts.append(core[prev:s])
            prev = s
    parts.append(core[prev:])
    return parts


def restore_tone_digits(phoneme_str: str) -> str:
    """Chèn tone digit cho syllable thanh ngang (espeak mới đã bỏ).

    Quy luật (phân tích thực nghiệm):
      - Mọi syllable thanh ngang -> digit "1"
      - Syllable thanh ngang là STRESS CHÍNH (ˈ) CUỐI CÙNG của mệnh đề -> digit "7"
        (vd: "tôi không" -> tôi=7 vì không chỉ có stress phụ ˌ;
              "ăn cơm không" -> cơm=7; "ba to ba to" -> to cuối=7)
    """
    tokens = [t for t in phoneme_str.split(" ") if t]
    token_segments = []
    for tok in tokens:
        m = re.match(r"^(.*?)([,;:.!?]*)$", tok)
        core, punct = m.group(1), m.group(2)
        token_segments.append((_split_syllables(core) if core else [], punct))

    # Segment cuối cùng có stress chính (ˈ sau cùng > ˌ)
    last_primary = None  # (token_idx, seg_idx)
    for ti, (segs, _punct) in enumerate(token_segments):
        for si, seg in enumerate(segs):
            if seg and seg.rfind("ˈ") > seg.rfind("ˌ"):
                last_primary = (ti, si)

    out_tokens = []
    for ti, (segs, punct) in enumerate(token_segments):
        if not segs:
            out_tokens.append(punct if punct else tokens[ti])
            continue
        new_segs = []
        for si, seg in enumerate(segs):
            if not seg:
                new_segs.append(seg)
                continue
            if _DIGIT_RE.search(seg) or "ɜ" in seg:
                new_segs.append(seg)
                continue
            digit = "7" if last_primary == (ti, si) else "1"
            new_segs.append(_insert_tone_digit(seg, digit))
        out_tokens.append("".join(new_segs) + punct)
    return " ".join(out_tokens)


# ---------------------------------------------------------------------------
# 8. Pipeline chính
# ---------------------------------------------------------------------------


def phonemize_sentence(sentence: str, voice: str = "vi") -> str:
    """Một câu -> chuỗi phoneme (đã có separator + tone digit)."""
    _espeak_set_voice(voice)

    parts = re.split(r"([,;:])", sentence)
    clauses: List[str] = []
    seps: List[str] = []
    current = ""
    for part in parts:
        if part in (",", ";", ":"):
            clauses.append(current)
            seps.append(part)
            current = ""
        else:
            current += part
    clauses.append(current)

    phoneme_parts: List[str] = []
    for i, clause in enumerate(clauses):
        clause = clause.strip()
        if not clause:
            continue
        ph = espeak_phonemize_clause(clause)
        ph = re.sub(r"\([^)]+\)", "", ph)  # bỏ marker (en)/(vi)
        ph = ph.strip()
        if not ph:
            continue
        # Clause-final ngang -> digit 7: cần mark BEFORE restore
        ph = restore_tone_digits(ph)
        if i < len(seps) and seps[i]:
            ph = ph + seps[i]
        phoneme_parts.append(ph)

    result = " ".join(p for p in phoneme_parts if p)
    result = re.sub(r"\s+", " ", result).strip()
    return result


def ttsx_phonemize(text: str, voice: str = "vi") -> List[str]:
    """Pipeline đầy đủ: text thô -> list chuỗi phoneme (mỗi câu 1 phần tử).

    Trả về [] nếu lỗi (caller fallback về pipeline piper mặc định).
    """
    try:
        processed = process_text_for_tts(text)
        chunks = split_sentences(processed)
        phonemes = []
        for chunk in chunks:
            ph = phonemize_sentence(chunk, voice=voice)
            if ph:
                phonemes.append(ph)
        return phonemes
    except Exception:
        return []


def phonemes_to_ids(phoneme_str: str, id_map) -> List[int]:
    """Phoneme string -> ID sequence chuẩn TTSx.

    NFD codepoint split rồi BOS, PAD, (phoneme+PAD)*, EOS.
    """
    chars = list(unicodedata.normalize("NFD", phoneme_str))
    ids: List[int] = list(id_map.get("^", [])) + list(id_map.get("_", []))
    for ch in chars:
        if ch in id_map:
            ids.extend(id_map[ch])
            ids.extend(id_map.get("_", []))
    ids.extend(id_map.get("$", []))
    return ids
