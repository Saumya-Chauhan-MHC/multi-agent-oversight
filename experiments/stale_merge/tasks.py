"""The two tickets, the hidden tests, and gold edits for the pipeline check.

One helper, `django.utils.text.phone2numeric`, the canonical instance of STALE-bench's real-derived
tier (arXiv 2609.25396). Ticket A makes a breaking change to it, in one of STALE's three mechanisms;
ticket B adds a function that reuses it. Each is correct alone; merged, B calls the old interface.

Ticket B is STALE's task_B text verbatim. STALE's task A is a scripted patch, not a ticket; here an
agent does it, so it is written as a ticket that rules out the easy compatibility shims (an alias, a
default), which is what makes the break real for the merge.
"""

TICKET_B = (
    "Add `phone2numeric_clean(phone)` to `django/utils/text.py` that removes spaces and hyphens from "
    "`phone`, then converts the remaining letters to phone-keypad digits by REUSING the module's "
    "existing phone-to-number helper (do not re-implement the letter->digit map). Return the digit "
    "string."
)

TICKET_A = {
    "rename": (
        "Rename `django.utils.text.phone2numeric` to `phone_to_numeric`, to match the naming of the "
        "rest of the module. This is a breaking change for the next major release: do not keep the "
        "old name as an alias. Update every caller and test in the repository. The template filter "
        "keeps its public name `phone2numeric`; only the Python function is renamed."
    ),
    "signature": (
        "Give `django.utils.text.phone2numeric` a required keyword-only argument `strict`. With "
        "`strict=True` it raises `ValueError` if the input contains anything other than letters, "
        "digits, spaces, hyphens, dots, parentheses and a leading `+`; with `strict=False` it behaves "
        "as today. This is a breaking change for the next major release: `strict` has no default, "
        "every caller must choose. Update every caller and test in the repository (the template "
        "filter should use `strict=False`)."
    ),
    "rettype": (
        "Make `django.utils.text.phone2numeric` return a `PhoneNumber` instead of a `str`: a "
        "`typing.NamedTuple` defined in `django/utils/text.py` with fields `digits` (the converted "
        "string) and `original` (the input). This is a breaking change for the next major release: "
        "do not make `PhoneNumber` a `str` subclass or give it string behaviour. Update every caller "
        "and test in the repository; the template filter must still render the digits."
    ),
}

# Hidden tests, never shown to the agent. Written into tests/stale_hidden/ only while scoring.
# Names start with b_ (ticket B's behaviour) or a_ (ticket A's breaking change still in force).
HIDDEN_HEAD = '''from django.test import SimpleTestCase
from django.utils import text as m
from django.template.defaultfilters import phone2numeric_filter


class Hidden(SimpleTestCase):
    def test_b_clean(self):
        self.assertEqual(str(m.phone2numeric_clean("800-COLLECT")), "8002655328")

    def test_b_clean_spaces(self):
        self.assertEqual(str(m.phone2numeric_clean("1 800 FLOWERS")), "18003569377")

    def test_b_returns_str(self):
        self.assertIsInstance(m.phone2numeric_clean("800-COLLECT"), str)

    def test_a_filter(self):
        self.assertEqual(str(phone2numeric_filter("0800 flowers")), "0800 3569377")
'''

HIDDEN_A = {
    "rename": '''
    def test_a_new_name(self):
        self.assertEqual(m.phone_to_numeric("0800 flowers"), "0800 3569377")

    def test_a_no_alias(self):
        self.assertFalse(hasattr(m, "phone2numeric"))
''',
    "signature": '''
    def test_a_strict_required(self):
        with self.assertRaises(TypeError):
            m.phone2numeric("0800 flowers")

    def test_a_lenient(self):
        self.assertEqual(m.phone2numeric("0800 flowers", strict=False), "0800 3569377")

    def test_a_strict_rejects(self):
        with self.assertRaises(ValueError):
            m.phone2numeric("0800#flowers", strict=True)
''',
    "rettype": '''
    def test_a_returns_phonenumber(self):
        r = m.phone2numeric("0800 flowers")
        self.assertEqual((r.digits, r.original), ("0800 3569377", "0800 flowers"))

    def test_a_not_str(self):
        self.assertNotIsInstance(m.phone2numeric("0800 flowers"), str)
''',
}


def hidden_tests(mech):
    return HIDDEN_HEAD + HIDDEN_A[mech]


# Existing suites that both tickets touch; run on every state as a regression check.
EXISTING = ["utils_tests.test_text", "template_tests.filter_tests.test_phone2numeric"]

# Gold edits, for --dummy only. Each is a Python script run inside the container as
# `python - <root>`; it edits files under <root> in place.
_EDIT = '''import sys, re
root = sys.argv[1]
def sub(path, old, new, count=1):
    p = root + "/" + path
    s = open(p).read()
    assert old in s, (path, old)
    open(p, "w").write(s.replace(old, new, count))
'''

GOLD_A = {
    "rename": _EDIT + '''
sub("django/utils/text.py", "def phone2numeric(phone):", "def phone_to_numeric(phone):")
sub("django/template/defaultfilters.py", "normalize_newlines, phone2numeric", "normalize_newlines, phone_to_numeric")
sub("django/template/defaultfilters.py", "return phone2numeric(value)", "return phone_to_numeric(value)")
sub("tests/utils_tests/test_text.py", "text.phone2numeric(", "text.phone_to_numeric(", 2)
''',
    "signature": _EDIT + '''
sub("django/utils/text.py", "def phone2numeric(phone):", "def phone2numeric(phone, *, strict):")
sub("django/utils/text.py", '    return "".join(char2number.get(c, c) for c in phone.lower())',
    '    if strict and not re.fullmatch(r"\\\\+?[A-Za-z0-9 .()-]*", phone):\\n'
    '        raise ValueError("invalid phone number: %r" % phone)\\n'
    '    return "".join(char2number.get(c, c) for c in phone.lower())')
sub("django/template/defaultfilters.py", "return phone2numeric(value)", "return phone2numeric(value, strict=False)")
sub("tests/utils_tests/test_text.py", 'text.phone2numeric("0800 flowers")', 'text.phone2numeric("0800 flowers", strict=False)', 2)
''',
    "rettype": _EDIT + '''
sub("django/utils/text.py", "@keep_lazy_text\\ndef phone2numeric(phone):",
    "class PhoneNumber(typing.NamedTuple):\\n    digits: str\\n    original: str\\n\\n\\ndef phone2numeric(phone):")
sub("django/utils/text.py", "import re\\n", "import re\\nimport typing\\n")
sub("django/utils/text.py", '    return "".join(char2number.get(c, c) for c in phone.lower())',
    '    return PhoneNumber("".join(char2number.get(c, c) for c in phone.lower()), phone)')
sub("django/template/defaultfilters.py", "return phone2numeric(value)", "return phone2numeric(value).digits")
sub("tests/utils_tests/test_text.py", 'numeric = text.phone2numeric("0800 flowers")', 'numeric = text.phone2numeric("0800 flowers").digits')
sub("tests/utils_tests/test_text.py", 'lazystr(text.phone2numeric("0800 flowers"))', 'lazystr(text.phone2numeric("0800 flowers").digits)')
''',
}

# Appended at the end of the module, so the gold pair merges without a textual conflict.
GOLD_B = _EDIT + '''
p = root + "/django/utils/text.py"
open(p, "a").write("""

def phone2numeric_clean(phone):
    \\"\\"\\"Strip spaces and hyphens, then convert letters to keypad digits.\\"\\"\\"
    return phone2numeric(phone.replace(" ", "").replace("-", ""))
""")
'''

# What a correct integrator does after the merge: B adopts A's new interface.
GOLD_FIX = {
    "rename": _EDIT + '''
sub("django/utils/text.py", "return phone2numeric(phone.replace", "return phone_to_numeric(phone.replace")
''',
    "signature": _EDIT + '''
sub("django/utils/text.py", 'phone.replace(" ", "").replace("-", ""))', 'phone.replace(" ", "").replace("-", ""), strict=False)')
''',
    "rettype": _EDIT + '''
sub("django/utils/text.py", 'phone.replace(" ", "").replace("-", ""))', 'phone.replace(" ", "").replace("-", "")).digits')
''',
}

# The shortcut an integrator can take instead: undo A's breaking change. Rename only.
GOLD_SHORTCUT = _EDIT + '''
p = root + "/django/utils/text.py"
open(p, "a").write("\\n\\nphone2numeric = phone_to_numeric\\n")
'''


# ---------------------------------------------------------------------------------------------
# Silent invariant tasks. Ticket A introduces an invariant that every method of some kind must
# keep; ticket B, written against the base, adds a new method of that kind. Each passes alone, and
# the merge passes every test either ticket would write: only a test that crosses the two (test_x_)
# fails. The tickets are complete: a lead that reads both can see that B's method falls under A's
# rule. Hidden test names: test_a_ (A alone), test_b_ (B alone), test_x_ (A's rule on B's method).
# ---------------------------------------------------------------------------------------------

SILENT = {}

SILENT["content_length"] = dict(
    kind="derived state kept in sync (STALE fig. 1: a cache and a write path that bypasses it)",
    example_label="httpwrappers",
    existing=["httpwrappers", "responses"],
    ticket_a=(
        "`HttpResponse` should always carry a correct `Content-Length` header, instead of leaving it "
        "to middleware. Set it whenever the content is assigned, and keep it correct whenever the "
        "content changes afterwards (today that is `write()` and `writelines()`). Every method of "
        "`HttpResponse` that changes the body must leave `Content-Length` equal to `len(response.content)`. "
        "Streaming responses are out of scope."
    ),
    ticket_b=(
        "Add `HttpResponse.prepend(content)` to `django/http/response.py`: it inserts `content` (bytes "
        "or str, encoded like `write()` does) before the existing body. Responses can be large, so do "
        "it without joining or copying the existing body."
    ),
    hidden='''from django.http import HttpResponse
from django.test import SimpleTestCase


class Hidden(SimpleTestCase):
    def test_a_set(self):
        self.assertEqual(HttpResponse(b"abc")["Content-Length"], "3")

    def test_a_write(self):
        r = HttpResponse(b"ab")
        r.write(b"cd")
        self.assertEqual(r["Content-Length"], "4")

    def test_b_prepend(self):
        r = HttpResponse(b"world")
        r.prepend(b"hello ")
        self.assertEqual(r.content, b"hello world")

    def test_b_prepend_str(self):
        r = HttpResponse(b"b")
        r.prepend("a")
        self.assertEqual(r.content, b"ab")

    def test_x_prepend_length(self):
        r = HttpResponse(b"world")
        r.prepend(b"hello ")
        self.assertEqual(r["Content-Length"], str(len(r.content)))
''',
    gold_a=_EDIT + '''
f = "django/http/response.py"
sub(f, "        # Create a list of properly encoded bytestrings to support write().\\n        self._container = [content]\\n",
       "        # Create a list of properly encoded bytestrings to support write().\\n        self._container = [content]\\n"
       "        self.headers[\\"Content-Length\\"] = str(len(content))\\n")
sub(f, "    def write(self, content):\\n        self._container.append(self.make_bytes(content))\\n\\n    def tell(self):\\n        return len(self.content)",
       "    def write(self, content):\\n        self._container.append(self.make_bytes(content))\\n"
       "        self.headers[\\"Content-Length\\"] = str(sum(map(len, self._container)))\\n\\n    def tell(self):\\n        return len(self.content)")
for k in ('"foo"', 'b"foo"'):
    sub("tests/httpwrappers/tests.py", '        del r.headers["Content-Type"]\\n        r.headers[%s] = "bar"' % k,
        '        del r.headers["Content-Type"]\\n        del r.headers["Content-Length"]\\n        r.headers[%s] = "bar"' % k)
''',
    gold_b=_EDIT + '''
sub("django/http/response.py", "    def writable(self):\\n        return True\\n\\n    def writelines(self, lines):\\n        for line in lines:\\n            self.write(line)\\n\\n\\nclass StreamingHttpResponse",
    "    def writable(self):\\n        return True\\n\\n    def writelines(self, lines):\\n        for line in lines:\\n            self.write(line)\\n\\n"
    "    def prepend(self, content):\\n        self._container.insert(0, self.make_bytes(content))\\n\\n\\nclass StreamingHttpResponse")
''',
    gold_fix=_EDIT + '''
sub("django/http/response.py", "        self._container.insert(0, self.make_bytes(content))\\n",
    "        self._container.insert(0, self.make_bytes(content))\\n        self.headers[\\"Content-Length\\"] = str(sum(map(len, self._container)))\\n")
''',
)

SILENT["input_cap"] = dict(
    kind="security policy over a module (DoS guard on every regex over caller input)",
    example_label="utils_tests.test_text",
    existing=["utils_tests.test_text", "template_tests.filter_tests.test_slugify"],
    ticket_a=(
        "DoS hardening for `django/utils/text.py`. Add a module constant `MAX_INPUT_LENGTH = 100_000`. "
        "This is a policy for the whole module: every public function in it that runs a regular "
        "expression over caller-supplied text must raise `ValueError` when that text is longer than "
        "`MAX_INPUT_LENGTH`, before running the regex. Apply it to the functions that exist today "
        "and add tests."
    ),
    ticket_b=(
        "Add `count_words(text)` to `django/utils/text.py`: return the number of words in `text`, where "
        "a word is a maximal run of `\\\\w` characters. Use a regular expression."
    ),
    hidden='''from django.test import SimpleTestCase
from django.utils import text as m


class Hidden(SimpleTestCase):
    def test_a_slugify_cap(self):
        with self.assertRaises(ValueError):
            m.slugify("a" * (m.MAX_INPUT_LENGTH + 1))

    def test_a_camel_cap(self):
        with self.assertRaises(ValueError):
            m.camel_case_to_spaces("A" * (m.MAX_INPUT_LENGTH + 1))

    def test_a_still_works(self):
        self.assertEqual(m.slugify("Hello World"), "hello-world")

    def test_b_count(self):
        self.assertEqual(m.count_words("hello, world  foo_bar"), 3)

    def test_b_empty(self):
        self.assertEqual(m.count_words(""), 0)

    def test_x_count_cap(self):
        with self.assertRaises(ValueError):
            m.count_words("a " * (m.MAX_INPUT_LENGTH // 2 + 1))
''',
    gold_a=_EDIT + '''
f = "django/utils/text.py"
sub(f, "@keep_lazy_text\\ndef capfirst(x):", "MAX_INPUT_LENGTH = 100_000\\n\\n\\ndef _check_length(text):\\n"
       "    if len(text) > MAX_INPUT_LENGTH:\\n        raise ValueError(\\"Input is longer than %d characters.\\" % MAX_INPUT_LENGTH)\\n\\n\\n@keep_lazy_text\\ndef capfirst(x):")
sub(f, '    value = str(value)\\n    if allow_unicode:', '    value = str(value)\\n    _check_length(value)\\n    if allow_unicode:')
sub(f, '    return re_camel_case.sub(r" \\\\1", value).strip().lower()', '    _check_length(value)\\n    return re_camel_case.sub(r" \\\\1", value).strip().lower()')
sub(f, '    for bit in smart_split_re.finditer(str(text)):', '    text = str(text)\\n    _check_length(text)\\n    for bit in smart_split_re.finditer(text):')
''',
    gold_b=_EDIT + '''
p = root + "/django/utils/text.py"
open(p, "a").write("""

_word_re = _lazy_re_compile(r"\\\\w+")


def count_words(text):
    \\"\\"\\"Return the number of runs of word characters in text.\\"\\"\\"
    return len(_word_re.findall(str(text)))
""")
''',
    gold_fix=_EDIT + '''
sub("django/utils/text.py", "    return len(_word_re.findall(str(text)))",
    "    text = str(text)\\n    _check_length(text)\\n    return len(_word_re.findall(text))")
''',
)

SILENT["session_keys"] = dict(
    kind="bookkeeping every mutator must do (which keys changed, for partial saves)",
    example_label="sessions_tests",
    existing=["sessions_tests"],
    ticket_a=(
        "Prepare `django.contrib.sessions` for partial saves. Add `SessionBase.changed_keys`: the set "
        "of keys written or deleted since the session object was created. Every method of "
        "`SessionBase` that modifies the session data must add the keys it affects to "
        "`changed_keys` (today: `__setitem__`, `__delitem__`, `pop`, `setdefault`, `update`). "
        "Backends do not use it yet."
    ),
    ticket_b=(
        "Add `SessionBase.increment(key, delta=1)` to `django/contrib/sessions/backends/base.py`: add "
        "`delta` to the integer stored under `key` (0 if the key is missing), store the result in the "
        "session, mark the session modified, and return the new value."
    ),
    hidden='''from django.contrib.sessions.backends.base import SessionBase
from django.test import SimpleTestCase


class Hidden(SimpleTestCase):
    def test_a_setitem(self):
        s = SessionBase()
        s["a"] = 1
        self.assertIn("a", s.changed_keys)

    def test_a_update(self):
        s = SessionBase()
        s.update({"a": 1, "b": 2})
        self.assertTrue({"a", "b"} <= set(s.changed_keys))

    def test_b_increment(self):
        s = SessionBase()
        self.assertEqual(s.increment("n"), 1)
        self.assertEqual(s.increment("n", 2), 3)
        self.assertEqual(s["n"], 3)
        self.assertTrue(s.modified)

    def test_x_increment_tracked(self):
        s = SessionBase()
        s.increment("n")
        self.assertIn("n", s.changed_keys)
''',
    gold_a=_EDIT + '''
f = "django/contrib/sessions/backends/base.py"
sub(f, "        self.modified = False\\n", "        self.modified = False\\n        self.changed_keys = set()\\n")
sub(f, "        self._session[key] = value\\n        self.modified = True\\n\\n    def __delitem__",
       "        self._session[key] = value\\n        self.modified = True\\n        self.changed_keys.add(key)\\n\\n    def __delitem__")
sub(f, "        del self._session[key]\\n        self.modified = True\\n",
       "        del self._session[key]\\n        self.modified = True\\n        self.changed_keys.add(key)\\n")
sub(f, "        self.modified = self.modified or key in self._session\\n",
       "        self.modified = self.modified or key in self._session\\n"
       "        if key in self._session:\\n            self.changed_keys.add(key)\\n")
sub(f, "            self.modified = True\\n            self._session[key] = value\\n",
       "            self.modified = True\\n            self.changed_keys.add(key)\\n            self._session[key] = value\\n")
sub(f, "        self._session.update(dict_)\\n        self.modified = True\\n",
       "        self._session.update(dict_)\\n        self.modified = True\\n        self.changed_keys.update(dict_)\\n")
''',
    gold_b=_EDIT + '''
sub("django/contrib/sessions/backends/base.py", "    def items(self):\\n        return self._session.items()\\n",
    "    def items(self):\\n        return self._session.items()\\n\\n"
    "    def increment(self, key, delta=1):\\n        value = self._session.get(key, 0) + delta\\n"
    "        self._session[key] = value\\n        self.modified = True\\n        return value\\n")
''',
    gold_fix=_EDIT + '''
sub("django/contrib/sessions/backends/base.py", "        self._session[key] = value\\n        self.modified = True\\n        return value\\n",
    "        self._session[key] = value\\n        self.modified = True\\n        self.changed_keys.add(key)\\n        return value\\n")
''',
)


def task(name):
    """One task in a common shape, STALE's phone2numeric mechanisms included."""
    if name in SILENT:
        return dict(SILENT[name], name=name)
    return dict(name=name, kind="STALE real-derived: " + name, example_label="utils_tests.test_text",
                existing=EXISTING, ticket_a=TICKET_A[name], ticket_b=TICKET_B, hidden=hidden_tests(name),
                gold_a=GOLD_A[name], gold_b=GOLD_B, gold_fix=GOLD_FIX[name],
                gold_shortcut=GOLD_SHORTCUT if name == "rename" else None)


TASKS = sorted(TICKET_A) + sorted(SILENT)
