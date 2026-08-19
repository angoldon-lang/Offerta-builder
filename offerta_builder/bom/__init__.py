"""Import e normalizzazione delle BOM dei distributori."""

from .base import RawTable
from .reader import read_tables
from .normalizer import normalize

__all__ = ["RawTable", "read_tables", "normalize"]
