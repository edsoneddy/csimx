"""Language wiring shared by the csimx tuning scripts (one place instead of a dict per script).

Keys of every language: lexer/parser/utils module + class names, the entry rule of the grammar and
the file extension. Mirrors csimx/language/parser.py and csimx.utils.get_extension_by_lang.
"""
_BASE = {
    "python_3": ("python_3", "Python3Lexer", "Python3Parser", "file_input", ".py"),
    "python_3_13": ("python_3_13", "PythonLexer", "PythonParser", "file_input", ".py"),
    "java_20": ("java_20", "Java20Lexer", "Java20Parser", "compilationUnit", ".java"),
    "java_24": ("java_24", "Java24Lexer", "Java24Parser", "compilationUnit", ".java"),
    "cpp_14": ("cpp_14", "CPP14Lexer", "CPP14Parser", "translationUnit", ".cpp"),
    "c": ("c", "CLexer", "CParser", "compilationUnit", ".c"),
    "kotlin": ("kotlin", "KotlinLexer", "KotlinParser", "kotlinFile", ".kt"),
}
LANGUAGES = sorted(_BASE)
# the order batch sweeps walk the languages in
DEFAULT_ORDER = ["java_20", "java_24", "cpp_14", "c", "kotlin", "python_3_13", "python_3"]

LANG_MODULES = {
    lang: {
        "lexer_module": f"csimx.{pkg}.{lexer}",
        "lexer_class": lexer,
        "parser_module": f"csimx.{pkg}.{parser}",
        "parser_class": parser,
        "utils_module": f"csimx.{pkg}.utils",
        "entry_rule": entry,
        "extension": ext,
    }
    for lang, (pkg, lexer, parser, entry, ext) in _BASE.items()
}
LANG_PARSE_CONFIG = LANG_MODULES
LANG_UTILS_MODULE = {lang: cfg["utils_module"] for lang, cfg in LANG_MODULES.items()}
EXTENSION_BY_LANG = {lang: cfg["extension"] for lang, cfg in LANG_MODULES.items()}
