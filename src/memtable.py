"""
Memtable Module

Purpose:
    In-memory sorted data structure for fast writes and reads.
    Serves as the first level of the LSM-tree storage hierarchy.

Key Features:
    - Sorted key-value storage using SortedDict
    - Size-based flush threshold
    - Tombstone support for deletes
    - Efficient point lookups

Design:
    Using sortedcontainers.SortedDict for O(log n) operations with
    simple, battle-tested implementation.
"""

from sortedcontainers import SortedDict
from typing import Optional, Iterator, Tuple
import sys


class Memtable:
    """
    In-memory sorted key-value store
    
    Stores recent writes in memory for fast access. When size exceeds
    threshold, it is flushed to disk as an SSTable.
    """
    
    TOMBSTONE = object()  # Sentinel value for deleted keys
    DEFAULT_MAX_SIZE = 4 * 1024 * 1024  # 4 MB
    
    def __init__(self, max_size_bytes: int = DEFAULT_MAX_SIZE):
        """
        Args:
            max_size_bytes: Maximum size in bytes before flush is triggered
        """
        self._data = SortedDict()
        self.max_size_bytes = max_size_bytes
        self._size_bytes = 0
    
    def put(self, key: bytes, value: bytes) -> None:
        """
        Insert or update a key-value pair
        
        Args:
            key: The key (must be bytes)
            value: The value (must be bytes)
        """
        if not isinstance(key, bytes):
            raise TypeError("Key must be bytes")
        if not isinstance(value, bytes):
            raise TypeError("Value must be bytes")
        
        # Calculate size delta
        old_size = self._get_entry_size(key, self._data.get(key))
        new_size = self._get_entry_size(key, value)
        
        # Update data
        self._data[key] = value # SortedDict tự động sort
        
        # Update size tracking
        self._size_bytes = self._size_bytes - old_size + new_size
    
    def get(self, key: bytes) -> Optional[bytes]:
        """
        Retrieve value for a key
        
        Args:
            key: The key to lookup
            
        Returns:
            The value if key exists and not deleted, None otherwise
        """
        if not isinstance(key, bytes):
            raise TypeError("Key must be bytes")
        
        value = self._data.get(key)
        
        if value is self.TOMBSTONE:
            # Key is deleted
            return None
        
        return value
    
    # Timeline:
    # 1. PUT(k1, v1) → SSTable[k1=v1]
    # 2. DELETE(k1) → Memtable[k1=TOMBSTONE]
    # 3. GET(k1) → Check Memtable trước → thấy TOMBSTONE → return None
    #             (không cần check SSTable)
    def delete(self, key: bytes) -> None:
        """
        Mark a key as deleted (insert tombstone)
        
        Args:
            key: The key to delete
        """
        if not isinstance(key, bytes):
            raise TypeError("Key must be bytes")
        
        # Calculate size delta
        old_size = self._get_entry_size(key, self._data.get(key))
        new_size = self._get_entry_size(key, self.TOMBSTONE)
        
        # Insert tombstone
        self._data[key] = self.TOMBSTONE
        
        # Update size tracking
        self._size_bytes = self._size_bytes - old_size + new_size
    
    def is_full(self) -> bool:
        """Check if memtable has reached size threshold"""
        return self._size_bytes >= self.max_size_bytes
    
    def size_bytes(self) -> int:
        """Get current size in bytes"""
        return self._size_bytes
    
    def num_entries(self) -> int:
        """Get number of entries (including tombstones)"""
        return len(self._data)
    
    def is_empty(self) -> bool:
        """Check if memtable is empty"""
        return len(self._data) == 0
    
    def iter_all(self) -> Iterator[Tuple[bytes, bytes]]:
        """
        Iterate over all entries in sorted order
        
        Yields:
            Tuples of (key, value) where value may be TOMBSTONE
        """
        for key, value in self._data.items():
            yield key, value
    
    def clear(self):
        """Clear all entries (called after successful flush)"""
        self._data.clear()
        self._size_bytes = 0
    
    def _get_entry_size(self, key: bytes, value) -> int:
        """
        Calculate approximate size of an entry
        
        Args:
            key: The key
            value: The value (may be TOMBSTONE or None)
            
        Returns:
            Estimated size in bytes
        """
        if value is None:
            # Entry doesn't exist
            return 0
        
        # Key size
        size = len(key)
        
        # Value size
        if value is self.TOMBSTONE:
            # Tombstone takes minimal space (just marker)
            size += 4  # Just the tombstone marker
        else:
            size += len(value)
        
        # Python object overhead (approximate)
        # Each entry has reference overhead in SortedDict
        size += sys.getsizeof(key) - len(key)  # Object overhead
        size += 48  # Approximate SortedDict node overhead
        
        return size
    
    def __len__(self):
        return len(self._data)
    
    def __repr__(self):
        return (f"Memtable(entries={len(self._data)}, "
                f"size={self._size_bytes}/{self.max_size_bytes} bytes)")

# Flush Process
# if memtable.is_full():  # _size_bytes >= 4MB
    # 1. Iterate tất cả entries (sorted order)
    # for key, value in memtable.iter_all():
    #     sstable_writer.add(key, value)  # Write to disk
    
    # 2. Finalize SSTable
    # sstable_writer.finalize()
    
    # 3. Clear Memtable
    # memtable.clear()  # _data.clear(), _size_bytes=0
    
    # 4. Truncate WAL
    # wal.truncate()  # Data đã an toàn trên disk
class MemtableIterator:
    """
    Iterator for merging multiple memtables/SSTables
    
    Used during compaction to iterate over entries in sorted order
    """
    
    def __init__(self, memtable: Memtable):
        """
        Args:
            memtable: The memtable to iterate over
        """
        self._iter = memtable.iter_all()
        self._current = None
        self._advance()
    
    def _advance(self):
        """Move to next entry"""
        try:
            self._current = next(self._iter)
        except StopIteration:
            self._current = None
    
    def peek(self) -> Optional[Tuple[bytes, bytes]]:
        """
        Peek at current entry without advancing
        
        Returns:
            (key, value) tuple or None if exhausted
        """
        return self._current
    
    def next(self) -> Optional[Tuple[bytes, bytes]]:
        """
        Get current entry and advance to next
        
        Returns:
            (key, value) tuple or None if exhausted
        """
        current = self._current
        if current is not None:
            self._advance()
        return current
    
    def has_next(self) -> bool:
        """Check if there are more entries"""
        return self._current is not None
