"""
SSTable (Sorted String Table) Module

Purpose:
    Persistent, immutable, sorted storage on disk.
    Efficiently stores key-value pairs with sparse indexing for fast lookups.

Key Features:
    - Immutable files (write once, read many)
    - Sparse index for binary search
    - Checksum for data integrity
    - Support for tombstones

File Structure:
    [Header][Data Block][Index Block][Footer]
    
    Header: Magic number, version, metadata
    Data Block: Sorted key-value entries
    Index Block: Sparse index (every 16th key)
    Footer: Index offset, checksum
"""

import os
import struct
from typing import Optional, Iterator, Tuple, List
from binascii import crc32


class SSTableWriter:
    """
    Writes an SSTable file from sorted key-value pairs
    
    Usage:
        writer = SSTableWriter("001.sst")
        for key, value in sorted_entries:
            writer.add(key, value)
        writer.finalize()
    """
    
    MAGIC_NUMBER = 0x5353544142424C45  # "SSTABBLE" in hex
    VERSION = 1
    INDEX_INTERVAL = 16  # Index every 16th key
    TOMBSTONE_MARKER = 0xFFFFFFFF
    
    def __init__(self, filepath: str):
        """
        Args:
            filepath: Path to SSTable file to create
        """
        self.filepath = filepath
        self._file = None
        self._num_entries = 0
        self._index_entries = []  # List of (key, offset)
        self._data_start = 0
        self._first_key = None
        self._last_key = None
        
        # Create directory if needed
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        
        # Open file
        self._file = open(filepath, 'wb')
        
        # Write placeholder header (will update later)
        self._write_header_placeholder()
    
    def _write_header_placeholder(self):
        """Write header placeholder (24 bytes)"""
        # Format: magic(8) + version(4) + num_entries(8) + reserved(4)
        header = struct.pack('<QIQ I', self.MAGIC_NUMBER, self.VERSION, 0, 0)
        self._file.write(header)
        self._data_start = self._file.tell()
    
    def add(self, key: bytes, value: Optional[bytes]) -> None:
        """
        Add a key-value entry (must be added in sorted order)
        
        Args:
            key: The key
            value: The value, or None for tombstone
        """
        if not isinstance(key, bytes):
            raise TypeError("Key must be bytes")
        if value is not None and not isinstance(value, bytes):
            raise TypeError("Value must be bytes or None")
        
        # Track first and last keys
        if self._first_key is None:
            self._first_key = key
        
        # Verify sorted order
        if self._last_key is not None and key <= self._last_key:
            raise ValueError(f"Keys must be added in sorted order: {key!r} <= {self._last_key!r}")
        self._last_key = key
        
        # Record offset for index
        offset = self._file.tell() # Vị trí hiện tại
        if self._num_entries % self.INDEX_INTERVAL == 0:
            self._index_entries.append((key, offset))
        
        # Write entry: key_size(4) + value_size(4) + key + value
        key_size = len(key)
        if value is None:
            # Tombstone
            value_size = self.TOMBSTONE_MARKER
            value_data = b''
        else:
            value_size = len(value)
            value_data = value
        
        entry = struct.pack('<II', key_size, value_size)
        entry += key + value_data
        
        self._file.write(entry)
        self._num_entries += 1
    
    def finalize(self) -> None:
        """
        Complete SSTable file by writing index and footer
        Must be called after all entries are added
        """
        # Write index block
        index_offset = self._file.tell()
        for key, offset in self._index_entries:
            # Format: key_size(4) + key + offset(8)
            index_entry = struct.pack('<I', len(key))
            index_entry += key
            index_entry += struct.pack('<Q', offset)
            self._file.write(index_entry)
        
        # Write footer: index_offset(8) + checksum(8) - placeholder first
        footer_offset = self._file.tell()
        footer = struct.pack('<QQ', index_offset, 0)  # Temporary checksum
        self._file.write(footer)
        
        # Update header with actual num_entries
        self._file.seek(0)
        header = struct.pack('<QIQ I', self.MAGIC_NUMBER, self.VERSION, 
                           self._num_entries, 0)
        self._file.write(header)
        
        # Flush everything before calculating checksum
        self._file.flush()
        os.fsync(self._file.fileno())
        
        # Calculate checksum over everything except the last 8 bytes (checksum itself)
        # This includes: header + data + index + index_offset (8 bytes)
        with open(self.filepath, 'rb') as f:
            data = f.read()  # Read entire file
        # Checksum is over all data except last 8 bytes
        data_to_check = data[:-8]  # Exclude placeholder checksum
        checksum = crc32(data_to_check) & 0xFFFFFFFF
        
        # Write actual footer with real checksum
        self._file.seek(footer_offset)
        footer = struct.pack('<QQ', index_offset, checksum)
        self._file.write(footer)
        
        # Flush and close
        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        self._file = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file:
            self._file.close()


class SSTableReader:
    """
    Reads an SSTable file with efficient lookups
    
    Uses sparse index and binary search for O(log n) lookups
    """
    
    MAGIC_NUMBER = 0x5353544142424C45
    TOMBSTONE_MARKER = 0xFFFFFFFF
    
    def __init__(self, filepath: str):
        """
        Args:
            filepath: Path to SSTable file
        """
        self.filepath = filepath
        
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"SSTable not found: {filepath}")
        
        # Load metadata
        self._load_metadata()
    
    def _load_metadata(self):
        """Load header, footer, and index"""
        with open(self.filepath, 'rb') as f:
            # Read header
            header_data = f.read(24)
            if len(header_data) < 24:
                raise ValueError("Invalid SSTable: header too short")
            
            magic, version, self.num_entries, _ = struct.unpack('<QIQ I', header_data)
            
            if magic != self.MAGIC_NUMBER:
                raise ValueError(f"Invalid SSTable: wrong magic number {magic:016x}")
            
            if version != 1:
                raise ValueError(f"Unsupported SSTable version: {version}")
            
            # Read footer (last 16 bytes)
            f.seek(-16, os.SEEK_END)
            footer_data = f.read(16)
            self.index_offset, stored_checksum = struct.unpack('<QQ', footer_data)
            
            # Verify checksum - calculate over header + data + index + index_offset
            f.seek(0)
            # Read up to the checksum field (which is at index_offset + 8)
            file_size = f.seek(0, os.SEEK_END)
            f.seek(0)
            data_to_check = f.read(file_size - 8)  # Exclude last 8 bytes (checksum)
            calculated_checksum = crc32(data_to_check) & 0xFFFFFFFF
            
            if stored_checksum != calculated_checksum:
                raise ValueError(
                    f"Checksum mismatch in {self.filepath}: "
                    f"stored={stored_checksum:016x}, calculated={calculated_checksum:016x}"
                )
            
            # Load index
            f.seek(self.index_offset)
            footer_start = f.seek(-16, os.SEEK_END)
            f.seek(self.index_offset)
            
            index_data = f.read(footer_start - self.index_offset)
            self.index = self._parse_index(index_data)
            
            self.data_start = 24  # Right after header
    
    def _parse_index(self, index_data: bytes) -> List[Tuple[bytes, int]]:
        """Parse index block into list of (key, offset) tuples"""
        index = []
        offset = 0
        
        while offset < len(index_data):
            # Read key_size
            if offset + 4 > len(index_data):
                break
            key_size = struct.unpack('<I', index_data[offset:offset+4])[0]
            offset += 4
            
            # Read key
            if offset + key_size > len(index_data):
                break
            key = index_data[offset:offset+key_size]
            offset += key_size
            
            # Read data offset
            if offset + 8 > len(index_data):
                break
            data_offset = struct.unpack('<Q', index_data[offset:offset+8])[0]
            offset += 8
            
            index.append((key, data_offset))
        
        return index
    
    def get(self, key: bytes) -> Optional[bytes]:
        """
        Lookup a key in the SSTable
        
        Args:
            key: The key to find
            
        Returns:
            The value if found, None if not found or deleted
        """
        if not isinstance(key, bytes):
            raise TypeError("Key must be bytes")
        
        # Binary search in sparse index to find scan start position
        scan_start = self._find_scan_start(key)
        
        # Linear scan from that position
        with open(self.filepath, 'rb') as f:
            f.seek(scan_start)
            
            # Scan up to 16 entries (or until we pass the key)
            for _ in range(16):
                # Check if we're past index block
                if f.tell() >= self.index_offset:
                    break
                
                # Read entry header
                header = f.read(8)
                if len(header) < 8:
                    break
                
                key_size, value_size = struct.unpack('<II', header)
                
                # Read key
                entry_key = f.read(key_size)
                
                if entry_key == key:
                    # Found it!
                    if value_size == self.TOMBSTONE_MARKER:
                        # Tombstone - key is deleted
                        return None
                    else:
                        # Read and return value
                        value = f.read(value_size)
                        return value
                elif entry_key > key:
                    # We've passed the key - it doesn't exist
                    break
                else:
                    # Skip value and continue
                    if value_size != self.TOMBSTONE_MARKER:
                        f.seek(value_size, os.SEEK_CUR)
        
        return None
    
    def _find_scan_start(self, key: bytes) -> int:
        """
        Binary search in sparse index to find where to start scanning
        
        Returns:
            File offset to start linear scan
        """
        if not self.index:
            return self.data_start
        
        # Binary search
        left, right = 0, len(self.index) - 1
        result_offset = self.data_start
        
        while left <= right:
            mid = (left + right) // 2
            mid_key, mid_offset = self.index[mid]
            
            if mid_key <= key:
                result_offset = mid_offset
                left = mid + 1
            else:
                right = mid - 1
        
        return result_offset
    
    def iter_all(self) -> Iterator[Tuple[bytes, Optional[bytes]]]:
        """
        Iterate over all entries in sorted order
        
        Yields:
            Tuples of (key, value) where value is None for tombstones
        """
        with open(self.filepath, 'rb') as f:
            f.seek(self.data_start)
            
            for _ in range(self.num_entries):
                # Read entry header
                header = f.read(8)
                if len(header) < 8:
                    break
                
                key_size, value_size = struct.unpack('<II', header)
                
                # Read key
                key = f.read(key_size)
                
                # Read value
                if value_size == self.TOMBSTONE_MARKER:
                    value = None
                else:
                    value = f.read(value_size)
                
                yield key, value
    
    def get_range(self, start_key: Optional[bytes] = None, 
                  end_key: Optional[bytes] = None) -> Iterator[Tuple[bytes, Optional[bytes]]]:
        """
        Get all entries in key range [start_key, end_key)
        
        Args:
            start_key: Start of range (inclusive), None for beginning
            end_key: End of range (exclusive), None for end
            
        Yields:
            Tuples of (key, value)
        """
        for key, value in self.iter_all():
            if start_key is not None and key < start_key:
                continue
            if end_key is not None and key >= end_key:
                break
            yield key, value
    
    def __repr__(self):
        return f"SSTableReader(filepath={self.filepath!r}, entries={self.num_entries})"
