"""Lexical stage of csimx: a cheap comparison of the token sequences of two files.

The structural stage (parse, normalize, prune, tree edit distance) is what csimx reports.
This stage never produces a reported index: `group` can use it to skip the structural
comparison of a pair whose tokens are too different (see `LexicalAtLeast`).
"""
from .distance import LexicalAtLeast, LexicalBound, LexicalDistance, LexicalIndex
from .tokenizer import Tokenize

__all__ = ["Tokenize", "LexicalDistance", "LexicalIndex", "LexicalBound", "LexicalAtLeast"]
