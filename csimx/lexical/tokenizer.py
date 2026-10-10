"""Tokenization for the lexical stage, with Pygments (one tokenizer for every language csimx supports)."""

# csimx language -> name of the Pygments lexer class
_LEXER_NAMES = {
    "python_3": "PythonLexer",
    "python_3_13": "PythonLexer",
    "java_20": "JavaLexer",
    "java_24": "JavaLexer",
    "cpp_14": "CppLexer",
    "c": "CLexer",
    "kotlin": "KotlinLexer",
}

_lexers = {}
_type_ids = {}


def _lexer(lang):
    if lang not in _LEXER_NAMES:
        raise ValueError(f"Unsupported language for the lexical stage: {lang}")
    lexer = _lexers.get(lang)
    if lexer is None:
        from pygments import lexers

        lexer = _lexers[lang] = getattr(lexers, _LEXER_NAMES[lang])()
    return lexer


def Tokenize(content, lang):
    """Token keys of `content`: comments and blanks dropped, names, numbers and strings
    generalized to their Pygments type, keywords, operators and punctuation kept as written."""
    from pygments import lex
    from pygments.token import STANDARD_TYPES, Token

    if not _type_ids:
        _type_ids.update({t: i for i, t in enumerate(STANDARD_TYPES)})
    kept_as_written = (Token.Punctuation, Token.Operator, Token.Keyword)
    keys = []
    in_string = False
    for token_type, text in lex(content, _lexer(lang)):
        if token_type in Token.Comment or not text.strip():
            continue
        # Pygments splits one string literal into several tokens; a run is one key.
        if token_type in Token.Literal.String:
            if not in_string:
                keys.append(_type_ids[Token.Literal.String])
            in_string = True
            continue
        in_string = False
        # `in` also matches subtypes (Keyword.Type, Operator.Word, ...)
        if any(token_type in kind for kind in kept_as_written) or token_type not in _type_ids:
            keys.append(text)
        else:
            keys.append(_type_ids[token_type])
    return keys
