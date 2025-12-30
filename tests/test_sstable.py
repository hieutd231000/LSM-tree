"""
Comprehensive test suite for SSTable

Tests:
    - Write and read operations
    - Sparse index lookups
    - Tombstone handling
    - Checksum verification
    - Range queries
    - Large files
"""

import unittest
import tempfile
import os
import shutil
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from sstable import SSTableWriter, SSTableReader
from memtable import Memtable


class TestSSTableWriter(unittest.TestCase):
    """Test SSTable writing"""
    
    def setUp(self):
        """Create temporary directory for each test"""
        self.test_dir = tempfile.mkdtemp()
        self.sst_path = os.path.join(self.test_dir, "test.sst")
    
    def tearDown(self):
        """Clean up temporary directory"""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_write_and_read_basic(self):
        """Test basic write and read operations"""
        # Write SSTable
        writer = SSTableWriter(self.sst_path)
        writer.add(b"key1", b"value1")
        writer.add(b"key2", b"value2")
        writer.add(b"key3", b"value3")
        writer.finalize()
        
        # Read SSTable
        reader = SSTableReader(self.sst_path)
        
        self.assertEqual(reader.get(b"key1"), b"value1")
        self.assertEqual(reader.get(b"key2"), b"value2")
        self.assertEqual(reader.get(b"key3"), b"value3")
        self.assertIsNone(reader.get(b"nonexistent"))
    
    def test_sorted_order_requirement(self):
        """Test that keys must be added in sorted order"""
        writer = SSTableWriter(self.sst_path)
        writer.add(b"key1", b"value1")
        writer.add(b"key2", b"value2")
        
        # Try to add out-of-order key
        with self.assertRaises(ValueError) as ctx:
            writer.add(b"key1", b"value_again")  # key1 < key2, wrong order
        
        self.assertIn("sorted order", str(ctx.exception))
    
    def test_tombstone_write_read(self):
        """Test writing and reading tombstones"""
        writer = SSTableWriter(self.sst_path)
        writer.add(b"key1", b"value1")
        writer.add(b"key2", None)  # Tombstone
        writer.add(b"key3", b"value3")
        writer.finalize()
        
        reader = SSTableReader(self.sst_path)
        
        self.assertEqual(reader.get(b"key1"), b"value1")
        self.assertIsNone(reader.get(b"key2"))  # Tombstone returns None
        self.assertEqual(reader.get(b"key3"), b"value3")
    
    def test_empty_sstable(self):
        """Test creating empty SSTable"""
        writer = SSTableWriter(self.sst_path)
        writer.finalize()
        
        reader = SSTableReader(self.sst_path)
        
        self.assertEqual(reader.num_entries, 0)
        self.assertIsNone(reader.get(b"any_key"))
    
    def test_context_manager(self):
        """Test using SSTableWriter as context manager"""
        with SSTableWriter(self.sst_path) as writer:
            writer.add(b"key1", b"value1")
            writer.add(b"key2", b"value2")
            writer.finalize()
        
        reader = SSTableReader(self.sst_path)
        self.assertEqual(reader.get(b"key1"), b"value1")


class TestSSTableReader(unittest.TestCase):
    """Test SSTable reading and lookups"""
    
    def setUp(self):
        """Create temporary directory and sample SSTable"""
        self.test_dir = tempfile.mkdtemp()
        self.sst_path = os.path.join(self.test_dir, "test.sst")
        
        # Create SSTable with 100 entries
        writer = SSTableWriter(self.sst_path)
        for i in range(100):
            key = f"key{i:03d}".encode()
            value = f"value{i}".encode()
            writer.add(key, value)
        writer.finalize()
        
        self.reader = SSTableReader(self.sst_path)
    
    def tearDown(self):
        """Clean up temporary directory"""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_sequential_reads(self):
        """Test reading all entries sequentially"""
        for i in range(100):
            key = f"key{i:03d}".encode()
            expected_value = f"value{i}".encode()
            
            value = self.reader.get(key)
            self.assertEqual(value, expected_value)
    
    def test_random_reads(self):
        """Test random access reads"""
        test_indices = [0, 25, 50, 75, 99]
        for i in test_indices:
            key = f"key{i:03d}".encode()
            expected_value = f"value{i}".encode()
            
            value = self.reader.get(key)
            self.assertEqual(value, expected_value)
    
    def test_nonexistent_keys(self):
        """Test reading keys that don't exist"""
        # Keys before first key
        self.assertIsNone(self.reader.get(b"aaa"))
        
        # Keys after last key
        self.assertIsNone(self.reader.get(b"zzz"))
        
        # Keys in middle but don't exist
        self.assertIsNone(self.reader.get(b"key999"))
    
    def test_iter_all(self):
        """Test iterating over all entries"""
        entries = list(self.reader.iter_all())
        
        self.assertEqual(len(entries), 100)
        
        # Verify sorted order
        prev_key = None
        for key, value in entries:
            if prev_key is not None:
                self.assertGreater(key, prev_key)
            prev_key = key
        
        # Verify first and last
        self.assertEqual(entries[0][0], b"key000")
        self.assertEqual(entries[99][0], b"key099")
    
    def test_get_range(self):
        """Test range queries"""
        # Range [key020, key030)
        entries = list(self.reader.get_range(b"key020", b"key030"))
        
        self.assertEqual(len(entries), 10)
        self.assertEqual(entries[0][0], b"key020")
        self.assertEqual(entries[9][0], b"key029")
    
    def test_get_range_from_start(self):
        """Test range query from beginning"""
        entries = list(self.reader.get_range(None, b"key010"))
        
        self.assertEqual(len(entries), 10)
        self.assertEqual(entries[0][0], b"key000")
        self.assertEqual(entries[9][0], b"key009")
    
    def test_get_range_to_end(self):
        """Test range query to end"""
        entries = list(self.reader.get_range(b"key090", None))
        
        self.assertEqual(len(entries), 10)
        self.assertEqual(entries[0][0], b"key090")
        self.assertEqual(entries[9][0], b"key099")
    
    def test_metadata(self):
        """Test SSTable metadata"""
        self.assertEqual(self.reader.num_entries, 100)
        self.assertTrue(hasattr(self.reader, 'index'))
        self.assertGreater(len(self.reader.index), 0)


class TestSSTableLarge(unittest.TestCase):
    """Test SSTable with large datasets"""
    
    def setUp(self):
        """Create temporary directory"""
        self.test_dir = tempfile.mkdtemp()
        self.sst_path = os.path.join(self.test_dir, "large.sst")
    
    def tearDown(self):
        """Clean up temporary directory"""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_large_sstable(self):
        """Test with 10,000 entries"""
        # Write
        writer = SSTableWriter(self.sst_path)
        for i in range(10000):
            key = f"key{i:05d}".encode()
            value = f"value{i}".encode()
            writer.add(key, value)
        writer.finalize()
        
        # Read
        reader = SSTableReader(self.sst_path)
        
        # Verify count
        self.assertEqual(reader.num_entries, 10000)
        
        # Verify random reads
        test_indices = [0, 100, 1000, 5000, 9999]
        for i in test_indices:
            key = f"key{i:05d}".encode()
            expected_value = f"value{i}".encode()
            value = reader.get(key)
            self.assertEqual(value, expected_value)
    
    def test_large_values(self):
        """Test with large value sizes"""
        writer = SSTableWriter(self.sst_path)
        
        # Add entries with 10KB values
        for i in range(100):
            key = f"key{i:03d}".encode()
            # Create exact 10KB value
            value = b'x' * 10000  # 10KB
            writer.add(key, value)
        
        writer.finalize()
        
        # Verify
        reader = SSTableReader(self.sst_path)
        for i in range(100):
            key = f"key{i:03d}".encode()
            value = reader.get(key)
            self.assertIsNotNone(value)
            self.assertEqual(len(value), 10000)


class TestSSTableFromMemtable(unittest.TestCase):
    """Test flushing Memtable to SSTable"""
    
    def setUp(self):
        """Create temporary directory"""
        self.test_dir = tempfile.mkdtemp()
        self.sst_path = os.path.join(self.test_dir, "flushed.sst")
    
    def tearDown(self):
        """Clean up temporary directory"""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_flush_memtable_to_sstable(self):
        """Test flushing memtable to SSTable"""
        # Create and populate memtable
        memtable = Memtable()
        memtable.put(b"key1", b"value1")
        memtable.put(b"key2", b"value2")
        memtable.delete(b"key3")  # Tombstone
        memtable.put(b"key4", b"value4")
        
        # Flush to SSTable
        writer = SSTableWriter(self.sst_path)
        for key, value in memtable.iter_all():
            # Convert TOMBSTONE to None for SSTable
            if value is Memtable.TOMBSTONE:
                value = None
            writer.add(key, value)
        writer.finalize()
        
        # Read from SSTable
        reader = SSTableReader(self.sst_path)
        
        self.assertEqual(reader.get(b"key1"), b"value1")
        self.assertEqual(reader.get(b"key2"), b"value2")
        self.assertIsNone(reader.get(b"key3"))  # Tombstone
        self.assertEqual(reader.get(b"key4"), b"value4")


class TestSSTableCorruption(unittest.TestCase):
    """Test SSTable corruption detection"""
    
    def setUp(self):
        """Create temporary directory and SSTable"""
        self.test_dir = tempfile.mkdtemp()
        self.sst_path = os.path.join(self.test_dir, "test.sst")
        
        # Create valid SSTable
        writer = SSTableWriter(self.sst_path)
        writer.add(b"key1", b"value1")
        writer.add(b"key2", b"value2")
        writer.finalize()
    
    def tearDown(self):
        """Clean up temporary directory"""
        shutil.rmtree(self.test_dir, ignore_errors=True)
    
    def test_corrupted_checksum(self):
        """Test detection of corrupted data via checksum"""
        # Corrupt a byte in the middle of the file
        with open(self.sst_path, 'r+b') as f:
            f.seek(50)
            byte = f.read(1)
            f.seek(50)
            f.write(bytes([byte[0] ^ 0xFF]))
        
        # Should raise ValueError on read
        with self.assertRaises(ValueError) as ctx:
            SSTableReader(self.sst_path)
        
        self.assertIn("Checksum mismatch", str(ctx.exception))
    
    def test_invalid_magic_number(self):
        """Test detection of invalid file format"""
        # Corrupt magic number
        with open(self.sst_path, 'r+b') as f:
            f.seek(0)
            f.write(b'\x00' * 8)
        
        with self.assertRaises(ValueError) as ctx:
            SSTableReader(self.sst_path)
        
        self.assertIn("magic number", str(ctx.exception))


def run_tests():
    """Run all SSTable tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestSSTableWriter))
    suite.addTests(loader.loadTestsFromTestCase(TestSSTableReader))
    suite.addTests(loader.loadTestsFromTestCase(TestSSTableLarge))
    suite.addTests(loader.loadTestsFromTestCase(TestSSTableFromMemtable))
    suite.addTests(loader.loadTestsFromTestCase(TestSSTableCorruption))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
