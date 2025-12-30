"""
Write-Ahead Log (WAL) Module

Purpose:
    Provides durability for LSM-tree by logging all write operations
    before they are applied to the in-memory structure.
    
Key Features:
    - Append-only log file
    - CRC32 checksums for corruption detection (bị lỗi, biến dạng)
        # Ví dụ:
        data = b"hello world"
        checksum = crc32(data)  # → 0x0d4a1185

        # Khi đọc lại:
        stored_checksum = 0x0d4a1185
        calculated_checksum = crc32(data)

        if stored_checksum == calculated_checksum:
            print("✓ Data OK")
        else:
            print("✗ Data corrupted!")
    - Crash recovery
    - Support for PUT and DELETE operations (tombstones)
    - Struct Pack
        # '<QII' là format string:
        # '<'  = Little-endian (byte order)
        # 'Q'  = unsigned long long (8 bytes, 64-bit)
        # 'I'  = unsigned int (4 bytes, 32-bit)
        # 'I'  = unsigned int (4 bytes, 32-bit)

File Format (core LevelDB/RocksDB):
    Each entry: [timestamp(8)][key_size(4)][value_size(4)][key][value][checksum(4)]
    
    - timestamp: uint64 (microseconds since epoch)
    - key_size: uint32 (length of key in bytes)
    - value_size: uint32 (length of value, 0xFFFFFFFF for tombstone)
    - key: bytes
    - value: bytes (empty for tombstone)
    - checksum: uint32 (CRC32 of all preceding fields)
"""

import os
import struct
import time
from typing import Iterator, Tuple, Optional
from binascii import crc32


class WALEntry:
    """Represents a single WAL entry (PUT or DELETE operation)"""
    
    TOMBSTONE_VALUE_SIZE = 0xFFFFFFFF  # Special marker for DELETE (số lớn nhất của uint32 (4 bytes))
    
    def __init__(self, key: bytes, value: Optional[bytes], timestamp: int = None):
        """
        Args:
            key: The key to write
            value: The value to write, or None for DELETE operation
            timestamp: Timestamp in microseconds (auto-generated if None)
        """
        if not isinstance(key, bytes):
            raise TypeError("Key must be bytes")
        if value is not None and not isinstance(value, bytes):
            raise TypeError("Value must be bytes or None")
            
        self.key = key
        self.value = value
        self.timestamp = timestamp or int(time.time() * 1_000_000)
        # is_tombstone -> Mục đích: Đánh dấu key đã bị XÓA (deleted)
        # Khi GET(key1):
            # 1. Check Memtable → Found TOMBSTONE → return None ✓
            # 2. Không cần check SSTable
        self.is_tombstone = value is None # (true nếu value là None)
    
    def serialize(self) -> bytes:
        """
        Serialize entry to bytes with checksum
        Returns:
            Serialized entry ready to write to WAL file
        """
        key_size = len(self.key)
        value_size = self.TOMBSTONE_VALUE_SIZE if self.is_tombstone else len(self.value)
        # b'': empty bytes (byte string rỗng)
        value_data = b'' if self.is_tombstone else self.value
        
        # Pack header: timestamp + key_size + value_size
        # Mục đích: Convert Python values → binary bytes (convert sang binary format cố định)
        header = struct.pack(
            '<QII',  # Little-endian: uint64, uint32, uint32
            self.timestamp,
            key_size,
            value_size
        )
        
        # Combine header + key + value
        data = header + self.key + value_data
        
        # Calculate CRC32 checksum
        checksum = crc32(data) & 0xFFFFFFFF  # (Mục đích: Đảm bảo checksum là 32-bit unsigned int)
        
        # Append checksum
        entry = data + struct.pack('<I', checksum)
        
        return entry
    
    @classmethod
    def deserialize(cls, data: bytes, offset: int = 0) -> Tuple['WALEntry', int]:
        """
        Deserialize entry from bytes and verify checksum
        
        Args:
            data: Raw bytes from WAL file
            offset: Starting position in data
            
        Returns:
            Tuple of (WALEntry, next_offset)
            
        Raises:
            ValueError: If data is corrupted or checksum doesn't match
        """
        # Read header (16 bytes: 8 + 4 + 4)
        if len(data) < offset + 16:
            raise ValueError("Insufficient data for WAL entry header")
        
        timestamp, key_size, value_size = struct.unpack('<QII', data[offset:offset+16])
        offset += 16
        
        # Read key
        if len(data) < offset + key_size:
            raise ValueError("Insufficient data for key")
        key = data[offset:offset+key_size]
        offset += key_size
        
        # Read value
        is_tombstone = (value_size == cls.TOMBSTONE_VALUE_SIZE)
        if is_tombstone:
            value = None
            actual_value_size = 0
        else:
            actual_value_size = value_size
            if len(data) < offset + actual_value_size:
                raise ValueError("Insufficient data for value")
            value = data[offset:offset+actual_value_size]
            offset += actual_value_size
        
        # Read and verify checksum
        if len(data) < offset + 4:
            raise ValueError("Insufficient data for checksum")
        stored_checksum = struct.unpack('<I', data[offset:offset+4])[0]
        offset += 4
        
        # Calculate expected checksum (all data except checksum itself)
        entry_data_end = offset - 4
        entry_data_start = offset - 4 - actual_value_size - key_size - 16
        calculated_checksum = crc32(data[entry_data_start:entry_data_end]) & 0xFFFFFFFF
        
        # Verify checksum
        if stored_checksum != calculated_checksum:
            raise ValueError(
                f"Checksum mismatch: stored={stored_checksum:08x}, "
                f"calculated={calculated_checksum:08x}"
            )
        
        entry = cls(key, value, timestamp)
        return entry, offset
    
    def __repr__(self):
        value_repr = "<tombstone>" if self.is_tombstone else f"{len(self.value)} bytes"
        return f"WALEntry(key={self.key!r}, value={value_repr}, ts={self.timestamp})"


class WAL:
    """
    Write-Ahead Log for durability
    
    All write operations (PUT/DELETE) are first written to WAL before
    being applied to the memtable. This ensures data is not lost on crash.
    """
    
    def __init__(self, filepath: str, sync_on_write: bool = True):
        """
        Args:
            filepath: Path to WAL file
            sync_on_write: If True, fsync after each write (slower but safer)
        """
        self.filepath = filepath
        self.sync_on_write = sync_on_write
        self._file = None
        self._open_file()
    
    def _open_file(self):
        """Open WAL file in append mode"""
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(os.path.abspath(self.filepath)), exist_ok=True)
        
        # Open in binary append mode
        self._file = open(self.filepath, 'ab', buffering=0)  # Unbuffered for safety
    
    def write(self, key: bytes, value: Optional[bytes]) -> None:
        """
        Write a PUT or DELETE entry to WAL
        
        Args:
            key: The key
            value: The value (None for DELETE)
        """
        entry = WALEntry(key, value)
        serialized = entry.serialize()
        
        self._file.write(serialized)
        
        # Force write to disk if requested
        if self.sync_on_write:
            self._file.flush()
            os.fsync(self._file.fileno())
    
    def read_all(self) -> Iterator[WALEntry]:
        """
        Read all entries from WAL
        
        Yields:
            WALEntry objects in order
            
        Note:
            Stops at first corrupted entry (partial write from crash)
        """
        if not os.path.exists(self.filepath):
            return
        
        with open(self.filepath, 'rb') as f:
            data = f.read()
        
        offset = 0
        while offset < len(data):
            try:
                entry, offset = WALEntry.deserialize(data, offset)
                yield entry
            except ValueError as e:
                # Corrupted entry (likely incomplete write during crash)
                # This is expected - just stop reading
                print(f"WAL: Stopped reading at offset {offset}: {e}")
                break
    
    def close(self):
        """Close WAL file"""
        if self._file:
            self._file.close()
            self._file = None
    
    def truncate(self):
        """
        Truncate (clear) the WAL file
        
        Called after successful memtable flush to disk
        """
        self.close()
        
        # Reopen in write mode (truncates file)
        with open(self.filepath, 'wb') as f:
            pass
        
        self._open_file()
    
    def delete(self):
        """Delete the WAL file"""
        self.close()
        if os.path.exists(self.filepath):
            os.remove(self.filepath)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def __repr__(self):
        return f"WAL(filepath={self.filepath!r})"
