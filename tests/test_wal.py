"""
Comprehensive test suite for WAL (Write-Ahead Log)

Tests:
    - Basic write and read operations
    - Tombstone (delete) operations
    - Crash recovery simulation
    - Checksum verification
    - Corruption detection
    - Large entries
"""

import unittest
import tempfile
import os
import shutil
from pathlib import Path

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from wal import WAL, WALEntry


class TestWALEntry(unittest.TestCase):
    """Test WALEntry serialization and deserialization"""
    
    def test_serialize_deserialize_put(self):
        """Test PUT operation serialization"""
        key = b"user:123"
        value = b"john_doe"
        
        entry = WALEntry(key, value)
        serialized = entry.serialize()
        
        # Deserialize
        recovered, offset = WALEntry.deserialize(serialized)
        
        self.assertEqual(recovered.key, key)
        self.assertEqual(recovered.value, value)
        self.assertEqual(recovered.is_tombstone, False)
        self.assertEqual(offset, len(serialized))
    
    def test_serialize_deserialize_delete(self):
        """Test DELETE operation (tombstone) serialization"""
        key = b"user:456"
        
        entry = WALEntry(key, None)  # None = tombstone
        serialized = entry.serialize()
        
        # Deserialize
        recovered, offset = WALEntry.deserialize(serialized)
        
        self.assertEqual(recovered.key, key)
        self.assertIsNone(recovered.value)
        self.assertTrue(recovered.is_tombstone)
    
    def test_multiple_entries_in_sequence(self):
        """Test deserializing multiple entries from byte stream"""
        entries = [
            WALEntry(b"key1", b"value1"),
            WALEntry(b"key2", b"value2"),
            WALEntry(b"key3", None),  # Delete
            WALEntry(b"key4", b"value4"),
        ]
        
        # Serialize all
        data = b''.join(e.serialize() for e in entries)
        
        # Deserialize all
        offset = 0
        recovered = []
        while offset < len(data):
            entry, offset = WALEntry.deserialize(data, offset)
            recovered.append(entry)
        
        # Verify
        self.assertEqual(len(recovered), len(entries))
        for orig, recov in zip(entries, recovered):
            self.assertEqual(orig.key, recov.key)
            self.assertEqual(orig.value, recov.value)
    
    def test_corrupted_checksum(self):
        """Test detection of corrupted data"""
        entry = WALEntry(b"test", b"data")
        serialized = bytearray(entry.serialize())
        
        # Corrupt a byte in the value part (not in header)
        # Header is 16 bytes, then key (4 bytes), then value
        serialized[20 + 2] ^= 0xFF  # Corrupt in value
        
        # Should raise ValueError
        with self.assertRaises(ValueError) as ctx:
            WALEntry.deserialize(bytes(serialized))
        
        self.assertIn("Checksum mismatch", str(ctx.exception))
    
    def test_large_entry(self):
        """Test with large key and value"""
        key = b"x" * 1000
        value = b"y" * 100000  # 100KB
        
        entry = WALEntry(key, value)
        serialized = entry.serialize()
        recovered, _ = WALEntry.deserialize(serialized)
        
        self.assertEqual(recovered.key, key)
        self.assertEqual(recovered.value, value)
    
    def test_empty_value(self):
        """Test with empty value (different from tombstone)"""
        key = b"empty_key"
        value = b""
        
        entry = WALEntry(key, value)
        self.assertFalse(entry.is_tombstone)
        
        serialized = entry.serialize()
        recovered, _ = WALEntry.deserialize(serialized)
        
        self.assertEqual(recovered.value, b"")
        self.assertFalse(recovered.is_tombstone)
    
    def test_type_validation(self):
        """Test type validation for key and value"""
        # Key must be bytes
        with self.assertRaises(TypeError):
            WALEntry("string_key", b"value")
        
        # Value must be bytes or None
        with self.assertRaises(TypeError):
            WALEntry(b"key", "string_value")


class TestWAL(unittest.TestCase):
    """Test WAL file operations"""
    
    def setUp(self):
        """Create temporary directory for each test"""
        self.test_dir = tempfile.mkdtemp()
        self.wal_path = os.path.join(self.test_dir, "test.wal")
    
    def tearDown(self):
        """Clean up temporary directory"""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_write_and_read(self):
        """Test basic write and read operations"""
        # Write entries
        wal = WAL(self.wal_path)
        wal.write(b"key1", b"value1")
        wal.write(b"key2", b"value2")
        wal.write(b"key3", b"value3")
        wal.close()
        
        # Read entries
        wal = WAL(self.wal_path, sync_on_write=False)
        entries = list(wal.read_all())
        wal.close()
        
        # Verify
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].key, b"key1")
        self.assertEqual(entries[0].value, b"value1")
        self.assertEqual(entries[1].key, b"key2")
        self.assertEqual(entries[2].key, b"key3")
    
    def test_tombstone_operations(self):
        """Test DELETE operations (tombstones)"""
        wal = WAL(self.wal_path)
        wal.write(b"key1", b"value1")
        wal.write(b"key2", None)  # Delete
        wal.write(b"key3", b"value3")
        wal.close()
        
        # Read and verify
        wal = WAL(self.wal_path, sync_on_write=False)
        entries = list(wal.read_all())
        wal.close()
        
        self.assertEqual(len(entries), 3)
        self.assertFalse(entries[0].is_tombstone)
        self.assertTrue(entries[1].is_tombstone)
        self.assertIsNone(entries[1].value)
        self.assertFalse(entries[2].is_tombstone)
    
    def test_crash_recovery(self):
        """Test recovery after simulated crash (incomplete write)"""
        wal = WAL(self.wal_path)
        wal.write(b"key1", b"value1")
        wal.write(b"key2", b"value2")
        
        # Simulate crash by writing incomplete entry
        incomplete_data = b"\x00" * 10  # Corrupted/incomplete entry
        wal._file.write(incomplete_data)
        wal._file.flush()
        wal.close()
        
        # Try to recover
        wal = WAL(self.wal_path, sync_on_write=False)
        entries = list(wal.read_all())
        wal.close()
        
        # Should recover first 2 entries, stop at corrupted one
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].key, b"key1")
        self.assertEqual(entries[1].key, b"key2")
    
    def test_empty_wal(self):
        """Test reading empty WAL"""
        wal = WAL(self.wal_path)
        entries = list(wal.read_all())
        wal.close()
        
        self.assertEqual(len(entries), 0)
    
    def test_truncate(self):
        """Test WAL truncation (after flush to SSTable)"""
        wal = WAL(self.wal_path)
        wal.write(b"key1", b"value1")
        wal.write(b"key2", b"value2")
        
        # Truncate
        wal.truncate()
        
        # Should be empty now
        entries = list(wal.read_all())
        self.assertEqual(len(entries), 0)
        
        # Should be able to write again
        wal.write(b"key3", b"value3")
        wal.close()
        
        # Verify
        wal = WAL(self.wal_path, sync_on_write=False)
        entries = list(wal.read_all())
        wal.close()
        
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].key, b"key3")
    
    def test_large_number_of_entries(self):
        """Test with 1000 entries"""
        wal = WAL(self.wal_path, sync_on_write=False)  # Faster without sync
        
        # Write 1000 entries
        for i in range(1000):
            key = f"key{i}".encode()
            value = f"value{i}".encode()
            wal.write(key, value)
        
        wal.close()
        
        # Read and verify
        wal = WAL(self.wal_path, sync_on_write=False)
        entries = list(wal.read_all())
        wal.close()
        
        self.assertEqual(len(entries), 1000)
        for i, entry in enumerate(entries):
            expected_key = f"key{i}".encode()
            expected_value = f"value{i}".encode()
            self.assertEqual(entry.key, expected_key)
            self.assertEqual(entry.value, expected_value)
    
    def test_context_manager(self):
        """Test WAL as context manager"""
        with WAL(self.wal_path) as wal:
            wal.write(b"key1", b"value1")
        
        # File should be closed
        # Verify data persisted
        with WAL(self.wal_path, sync_on_write=False) as wal:
            entries = list(wal.read_all())
        
        self.assertEqual(len(entries), 1)
    
    def test_delete_wal(self):
        """Test WAL deletion"""
        wal = WAL(self.wal_path)
        wal.write(b"key1", b"value1")
        wal.delete()
        
        # File should not exist
        self.assertFalse(os.path.exists(self.wal_path))


def run_tests():
    """Run all WAL tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestWALEntry))
    suite.addTests(loader.loadTestsFromTestCase(TestWAL))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
