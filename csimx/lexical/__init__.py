"""Lexical stage: compares token sequences so `group` can skip very different pairs.
It never produces a reported index."""
from .distance import LexicalAtLeast, LexicalBound, LexicalDistance, LexicalIndex
from .tokenizer import Tokenize

__all__ = ["Tokenize", "LexicalDistance", "LexicalIndex", "LexicalBound", "LexicalAtLeast"]
