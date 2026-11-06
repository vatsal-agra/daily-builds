"""Glyph-name tables: the 258 Macintosh standard glyph names (post format 2), the PDF
Standard/WinAnsi/MacRoman/MacExpert-less encodings, and a name->Unicode map."""
import unicodedata

MAC_GLYPH_NAMES = (
    ".notdef .null nonmarkingreturn space exclam quotedbl numbersign dollar percent ampersand quotesingle parenleft "
    "parenright asterisk plus comma hyphen period slash zero one two three four five six seven eight nine colon "
    "semicolon less equal greater question at A B C D E F G H I J K L M N O P Q R S T U V W X Y Z bracketleft "
    "backslash bracketright asciicircum underscore grave a b c d e f g h i j k l m n o p q r s t u v w x y z "
    "braceleft bar braceright asciitilde Adieresis Aring Ccedilla Eacute Ntilde Odieresis Udieresis aacute agrave "
    "acircumflex adieresis atilde aring ccedilla eacute egrave ecircumflex edieresis iacute igrave icircumflex "
    "idieresis ntilde oacute ograve ocircumflex odieresis otilde uacute ugrave ucircumflex udieresis dagger degree "
    "cent sterling section bullet paragraph germandbls registered copyright trademark acute dieresis notequal AE "
    "Oslash infinity plusminus lessequal greaterequal yen mu partialdiff summation product pi integral ordfeminine "
    "ordmasculine Omega ae oslash questiondown exclamdown logicalnot radical florin approxequal Delta guillemotleft "
    "guillemotright ellipsis nonbreakingspace Agrave Atilde Otilde OE oe endash emdash quotedblleft quotedblright "
    "quoteleft quoteright divide lozenge ydieresis Ydieresis fraction currency guilsinglleft guilsinglright fi fl "
    "daggerdbl periodcentered quotesinglbase quotedblbase perthousand Acircumflex Ecircumflex Aacute Edieresis "
    "Egrave Iacute Icircumflex Idieresis Igrave Oacute Ocircumflex apple Ograve Uacute Ucircumflex Ugrave dotlessi "
    "circumflex tilde macron breve dotaccent ring cedilla hungarumlaut ogonek caron Lslash lslash Scaron scaron "
    "Zcaron zcaron brokenbar Eth eth Yacute yacute Thorn thorn minus multiply onesuperior twosuperior "
    "threesuperior onehalf onequarter threequarters franc Gbreve gbreve Idotaccent Scedilla scedilla Cacute cacute "
    "Ccaron ccaron dcroat").split()

# Names whose Unicode value is not derivable from unicodedata.
_SPECIAL = {
    "space": 0x20, "nbspace": 0xA0, "nonbreakingspace": 0xA0, "hyphen": 0x2D, "sfthyphen": 0xAD, "softhyphen": 0xAD,
    "bullet": 0x2022, "endash": 0x2013, "emdash": 0x2014, "quoteleft": 0x2018, "quoteright": 0x2019,
    "quotesinglbase": 0x201A, "quotedblleft": 0x201C, "quotedblright": 0x201D, "quotedblbase": 0x201E,
    "dagger": 0x2020, "daggerdbl": 0x2021, "ellipsis": 0x2026, "perthousand": 0x2030, "guilsinglleft": 0x2039,
    "guilsinglright": 0x203A, "fraction": 0x2044, "Euro": 0x20AC, "trademark": 0x2122, "minus": 0x2212,
    "fi": 0xFB01, "fl": 0xFB02, "ff": 0xFB00, "ffi": 0xFB03, "ffl": 0xFB04, "florin": 0x192, "circumflex": 0x2C6,
    "tilde": 0x2DC, "caron": 0x2C7, "breve": 0x2D8, "dotaccent": 0x2D9, "ring": 0x2DA, "ogonek": 0x2DB,
    "hungarumlaut": 0x2DD, "macron": 0xAF, "dieresis": 0xA8, "acute": 0xB4, "grave": 0x60, "cedilla": 0xB8,
    "asciicircum": 0x5E, "asciitilde": 0x7E, "quotesingle": 0x27, "quotedbl": 0x22, "numbersign": 0x23,
    "dollar": 0x24, "percent": 0x25, "ampersand": 0x26, "parenleft": 0x28, "parenright": 0x29, "asterisk": 0x2A,
    "plus": 0x2B, "comma": 0x2C, "period": 0x2E, "slash": 0x2F, "colon": 0x3A, "semicolon": 0x3B, "less": 0x3C,
    "equal": 0x3D, "greater": 0x3E, "question": 0x3F, "at": 0x40, "bracketleft": 0x5B, "backslash": 0x5C,
    "bracketright": 0x5D, "underscore": 0x5F, "braceleft": 0x7B, "bar": 0x7C, "braceright": 0x7D, "exclam": 0x21,
    "zero": 0x30, "one": 0x31, "two": 0x32, "three": 0x33, "four": 0x34, "five": 0x35, "six": 0x36, "seven": 0x37,
    "eight": 0x38, "nine": 0x39, "exclamdown": 0xA1, "cent": 0xA2, "sterling": 0xA3, "currency": 0xA4, "yen": 0xA5,
    "brokenbar": 0xA6, "section": 0xA7, "copyright": 0xA9, "ordfeminine": 0xAA, "guillemotleft": 0xAB,
    "logicalnot": 0xAC, "registered": 0xAE, "degree": 0xB0, "plusminus": 0xB1, "twosuperior": 0xB2,
    "threesuperior": 0xB3, "mu": 0xB5, "paragraph": 0xB6, "periodcentered": 0xB7, "onesuperior": 0xB9,
    "ordmasculine": 0xBA, "guillemotright": 0xBB, "onequarter": 0xBC, "onehalf": 0xBD, "threequarters": 0xBE,
    "questiondown": 0xBF, "multiply": 0xD7, "divide": 0xF7, "germandbls": 0xDF, "AE": 0xC6, "ae": 0xE6,
    "Oslash": 0xD8, "oslash": 0xF8, "Eth": 0xD0, "eth": 0xF0, "Thorn": 0xDE, "thorn": 0xFE, "OE": 0x152,
    "oe": 0x153, "Scaron": 0x160, "scaron": 0x161, "Zcaron": 0x17D, "zcaron": 0x17E, "Ydieresis": 0x178,
    "Lslash": 0x141, "lslash": 0x142, "dotlessi": 0x131, "infinity": 0x221E, "notequal": 0x2260,
    "lessequal": 0x2264, "greaterequal": 0x2265, "partialdiff": 0x2202, "summation": 0x2211, "product": 0x220F,
    "pi": 0x3C0, "integral": 0x222B, "Omega": 0x3A9, "radical": 0x221A, "approxequal": 0x2248, "Delta": 0x394,
    "lozenge": 0x25CA, "franc": 0x20A3, "arrowright": 0x2192, "arrowleft": 0x2190, "arrowup": 0x2191,
    "arrowdown": 0x2193, "checkmark": 0x2713, "apple": 0xF8FF,
}
_ACCENTS = {"grave": "̀", "acute": "́", "circumflex": "̂", "tilde": "̃", "macron": "̄",
            "breve": "̆", "dotaccent": "̇", "dieresis": "̈", "ring": "̊", "hungarumlaut": "̋",
            "caron": "̌", "cedilla": "̧", "ogonek": "̨"}
_cache = {}


def name_to_unicode(name):
    """Glyph name -> unicode string ('' if unknown). Handles uniXXXX, uXXXX, ligature suffixes, X.alt."""
    if name in _cache:
        return _cache[name]
    r = _n2u(name)
    _cache[name] = r
    return r


def _n2u(name):
    if not name or name == ".notdef":
        return ""
    base = name.split(".")[0]
    if "_" in base:
        return "".join(_n2u(p) for p in base.split("_"))
    if base in _SPECIAL:
        return chr(_SPECIAL[base])
    if len(base) == 1:
        return base
    if base.startswith("uni") and len(base) >= 7 and all(c in "0123456789ABCDEF" for c in base[3:]):
        try:
            return "".join(chr(int(base[i:i + 4], 16)) for i in range(3, len(base) - 3, 4))
        except ValueError:
            return ""
    if base.startswith("u") and 5 <= len(base) <= 7 and all(c in "0123456789ABCDEF" for c in base[1:]):
        return chr(int(base[1:], 16))
    for acc, comb in _ACCENTS.items():
        if base.endswith(acc) and len(base) > len(acc) and base[:-len(acc)].isalpha():
            letter = base[:-len(acc)]
            if len(letter) == 1:
                return unicodedata.normalize("NFC", letter + comb)
    for n in ("Cacute", "cacute", "Ccaron", "ccaron", "Gbreve", "gbreve", "Idotaccent", "Scedilla", "scedilla", "dcroat"):
        pass
    try:
        return unicodedata.lookup({"Idotaccent": "LATIN CAPITAL LETTER I WITH DOT ABOVE", "Scedilla": "LATIN CAPITAL LETTER S WITH CEDILLA", "scedilla": "LATIN SMALL LETTER S WITH CEDILLA", "Gbreve": "LATIN CAPITAL LETTER G WITH BREVE", "gbreve": "LATIN SMALL LETTER G WITH BREVE", "Cacute": "LATIN CAPITAL LETTER C WITH ACUTE", "cacute": "LATIN SMALL LETTER C WITH ACUTE", "Ccaron": "LATIN CAPITAL LETTER C WITH CARON", "ccaron": "LATIN SMALL LETTER C WITH CARON", "dcroat": "LATIN SMALL LETTER D WITH STROKE"}.get(base, "x\0"))
    except KeyError:
        return ""


def _mk(table):
    return {i: n for i, n in table}


# WinAnsi (cp1252) derived programmatically; MacRoman via codec.
def _from_codec(codec, fixups=None):
    enc = {}
    for c in range(32, 256):
        try:
            u = bytes([c]).decode(codec)
        except UnicodeDecodeError:
            continue
        enc[c] = u
    return enc


_rev = {}


def unicode_to_name(u):
    if not _rev:
        for n, v in _SPECIAL.items():
            _rev.setdefault(chr(v), n)
        for n in MAC_GLYPH_NAMES:
            ch = _n2u(n)
            if len(ch) == 1:
                _rev.setdefault(ch, n)
    if u in _rev:
        return _rev[u]
    if len(u) == 1 and u.isalnum() and ord(u) < 128:
        return u
    return "uni%04X" % ord(u[0])


# Unicode per code for the base encodings (names derived from Unicode via unicode_to_name when needed)
WIN_ANSI = _from_codec("cp1252")
WIN_ANSI[0x7F] = "•"
for _c in (0x81, 0x8D, 0x8F, 0x90, 0x9D):
    WIN_ANSI[_c] = "•"
WIN_ANSI[0xA0] = " "
WIN_ANSI[0xAD] = "-"
MAC_ROMAN = _from_codec("mac_roman")
MAC_ROMAN[0xCA] = " "
STANDARD = {}
for _c in range(32, 127):
    STANDARD[_c] = chr(_c)
STANDARD[0x27] = "’"
STANDARD[0x60] = "‘"
STANDARD.update({0xA1: "¡", 0xA2: "¢", 0xA3: "£", 0xA4: "⁄", 0xA5: "¥", 0xA6: "ƒ", 0xA7: "§", 0xA8: "¤", 0xA9: "'",
                 0xAA: "“", 0xAB: "«", 0xAC: "‹", 0xAD: "›", 0xAE: "ﬁ", 0xAF: "ﬂ", 0xB1: "–", 0xB2: "†",
                 0xB3: "‡", 0xB4: "·", 0xB6: "¶", 0xB7: "•", 0xB8: "‚", 0xB9: "„", 0xBA: "”", 0xBB: "»",
                 0xBC: "…", 0xBD: "‰", 0xBF: "¿", 0xC1: "`", 0xC2: "´", 0xC3: "ˆ", 0xC4: "˜", 0xC5: "¯", 0xC6: "˘",
                 0xC7: "˙", 0xC8: "¨", 0xCA: "˚", 0xCB: "¸", 0xCD: "˝", 0xCE: "˛", 0xCF: "ˇ", 0xD0: "—",
                 0xE1: "Æ", 0xE3: "ª", 0xE8: "Ł", 0xE9: "Ø", 0xEA: "Œ", 0xEB: "º", 0xF1: "æ", 0xF5: "ı",
                 0xF8: "ł", 0xF9: "ø", 0xFA: "œ", 0xFB: "ß"})
BASE_ENCODINGS = {"WinAnsiEncoding": WIN_ANSI, "MacRomanEncoding": MAC_ROMAN, "StandardEncoding": STANDARD}
