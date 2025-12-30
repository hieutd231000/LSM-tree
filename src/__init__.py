"""
LSM-Tree Implementation

A simple Log-Structured Merge Tree key-value store.

Main components:
    - WAL: Write-Ahead Log for durability
    - Memtable: In-memory sorted storage
    - SSTable: On-disk sorted storage
"""

from .wal import WAL, WALEntry
from .memtable import Memtable, MemtableIterator
from .sstable import SSTableReader, SSTableWriter

__version__ = "0.1.0"
__all__ = [
    'WAL',
    'WALEntry',
    'Memtable',
    'MemtableIterator',
    'SSTableReader',
    'SSTableWriter',
]
