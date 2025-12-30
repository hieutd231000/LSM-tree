"""
Comprehensive test suite for Memtable

Tests:
    - Basic put and get operations
    - Delete operations (tombstones)
    - Size tracking and threshold
    - Sorted iteration
    - Edge cases
"""

import unittest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from memtable import Memtable, MemtableIterator


class TestMemtable(unittest.TestCase):
    """Test Memtable operations"""
    
    def setUp(self):
        """Create fresh memtable for each test"""
        self.memtable = Memtable(max_size_bytes=4 * 1024 * 1024)  # 4MB
    
    def test_put_and_get(self):
        """Test basic PUT and GET operations"""
        self.memtable.put(b"key1", b"value1")
        self.memtable.put(b"key2", b"value2")
        self.memtable.put(b"key3", b"value3")
        
        self.assertEqual(self.memtable.get(b"key1"), b"value1")
        self.assertEqual(self.memtable.get(b"key2"), b"value2")
        self.assertEqual(self.memtable.get(b"key3"), b"value3")
    
    def test_get_nonexistent_key(self):
        """Test GET on key that doesn't exist"""
        self.memtable.put(b"key1", b"value1")
        
        result = self.memtable.get(b"nonexistent")
        self.assertIsNone(result)
    
    def test_update_existing_key(self):
        """Test updating value for existing key"""
        self.memtable.put(b"key1", b"old_value")
        self.assertEqual(self.memtable.get(b"key1"), b"old_value")
        
        self.memtable.put(b"key1", b"new_value")
        self.assertEqual(self.memtable.get(b"key1"), b"new_value")
    
    def test_delete_operation(self):
        """Test DELETE operation (tombstone)"""
        self.memtable.put(b"key1", b"value1")
        self.assertEqual(self.memtable.get(b"key1"), b"value1")
        
        self.memtable.delete(b"key1")
        self.assertIsNone(self.memtable.get(b"key1"))
    
    def test_delete_nonexistent_key(self):
        """Test DELETE on key that doesn't exist"""
        # Should not raise error
        self.memtable.delete(b"nonexistent")
        self.assertIsNone(self.memtable.get(b"nonexistent"))
    
    def test_sorted_iteration(self):
        """Test that iteration returns entries in sorted order"""
        # Insert in random order
        keys = [b"zebra", b"alpha", b"beta", b"gamma", b"delta"]
        for i, key in enumerate(keys):
            self.memtable.put(key, f"value{i}".encode())
        
        # Iterate and verify sorted order
        iterated_keys = [key for key, _ in self.memtable.iter_all()]
        expected = sorted(keys)
        
        self.assertEqual(iterated_keys, expected)
    
    def test_size_tracking(self):
        """Test that size is tracked correctly"""
        initial_size = self.memtable.size_bytes()
        
        # Add entry
        self.memtable.put(b"key1", b"value1")
        size_after_put = self.memtable.size_bytes()
        
        self.assertGreater(size_after_put, initial_size)
        
        # Update with larger value
        self.memtable.put(b"key1", b"much_larger_value_here")
        size_after_update = self.memtable.size_bytes()
        
        self.assertGreater(size_after_update, size_after_put)
    
    def test_is_full_threshold(self):
        """Test that is_full() works correctly"""
        # Create small memtable
        small_memtable = Memtable(max_size_bytes=1000)
        
        self.assertFalse(small_memtable.is_full())
        
        # Add entries until full
        for i in range(100):
            small_memtable.put(f"key{i}".encode(), b"x" * 50)
            if small_memtable.is_full():
                break
        
        self.assertTrue(small_memtable.is_full())
    
    def test_num_entries(self):
        """Test num_entries() returns correct count"""
        self.assertEqual(self.memtable.num_entries(), 0)
        
        self.memtable.put(b"key1", b"value1")
        self.assertEqual(self.memtable.num_entries(), 1)
        
        self.memtable.put(b"key2", b"value2")
        self.assertEqual(self.memtable.num_entries(), 2)
        
        # Update doesn't increase count
        self.memtable.put(b"key1", b"new_value")
        self.assertEqual(self.memtable.num_entries(), 2)
        
        # Delete doesn't decrease count (tombstone remains)
        self.memtable.delete(b"key1")
        self.assertEqual(self.memtable.num_entries(), 2)
    
    def test_clear(self):
        """Test clear() empties memtable"""
        self.memtable.put(b"key1", b"value1")
        self.memtable.put(b"key2", b"value2")
        
        self.assertFalse(self.memtable.is_empty())
        
        self.memtable.clear()
        
        self.assertTrue(self.memtable.is_empty())
        self.assertEqual(self.memtable.num_entries(), 0)
        self.assertEqual(self.memtable.size_bytes(), 0)
    
    def test_large_number_of_entries(self):
        """Test with 10,000 entries"""
        for i in range(10000):
            key = f"key{i:05d}".encode()
            value = f"value{i}".encode()
            self.memtable.put(key, value)
        
        # Verify count
        self.assertEqual(self.memtable.num_entries(), 10000)
        
        # Verify random lookups
        self.assertEqual(self.memtable.get(b"key00000"), b"value0")
        self.assertEqual(self.memtable.get(b"key05000"), b"value5000")
        self.assertEqual(self.memtable.get(b"key09999"), b"value9999")
        
        # Verify sorted iteration
        prev_key = None
        for key, _ in self.memtable.iter_all():
            if prev_key is not None:
                self.assertGreater(key, prev_key)
            prev_key = key
    
    def test_empty_value(self):
        """Test with empty byte string as value"""
        self.memtable.put(b"empty_key", b"")
        
        result = self.memtable.get(b"empty_key")
        self.assertEqual(result, b"")
        self.assertIsNotNone(result)  # Different from None (deleted)
    
    def test_type_validation(self):
        """Test type validation for keys and values"""
        # Key must be bytes
        with self.assertRaises(TypeError):
            self.memtable.put("string_key", b"value")
        
        with self.assertRaises(TypeError):
            self.memtable.get("string_key")
        
        # Value must be bytes
        with self.assertRaises(TypeError):
            self.memtable.put(b"key", "string_value")
    
    def test_tombstone_in_iteration(self):
        """Test that tombstones appear in iteration"""
        self.memtable.put(b"key1", b"value1")
        self.memtable.put(b"key2", b"value2")
        self.memtable.delete(b"key1")  # Tombstone
        
        entries = list(self.memtable.iter_all())
        
        self.assertEqual(len(entries), 2)
        # key1 should have TOMBSTONE marker
        key1_entry = [e for e in entries if e[0] == b"key1"][0]
        self.assertIs(key1_entry[1], Memtable.TOMBSTONE)


class TestMemtableIterator(unittest.TestCase):
    """Test MemtableIterator"""
    
    def setUp(self):
        """Create memtable with test data"""
        self.memtable = Memtable()
        self.memtable.put(b"key1", b"value1")
        self.memtable.put(b"key2", b"value2")
        self.memtable.put(b"key3", b"value3")
    
    def test_basic_iteration(self):
        """Test basic iterator operations"""
        iterator = MemtableIterator(self.memtable)
        
        self.assertTrue(iterator.has_next())
        
        entry1 = iterator.next()
        self.assertEqual(entry1, (b"key1", b"value1"))
        
        entry2 = iterator.next()
        self.assertEqual(entry2, (b"key2", b"value2"))
        
        entry3 = iterator.next()
        self.assertEqual(entry3, (b"key3", b"value3"))
        
        self.assertFalse(iterator.has_next())
        self.assertIsNone(iterator.next())
    
    def test_peek(self):
        """Test peek() doesn't advance iterator"""
        iterator = MemtableIterator(self.memtable)
        
        entry1 = iterator.peek()
        self.assertEqual(entry1, (b"key1", b"value1"))
        
        # Peek again - should return same entry
        entry1_again = iterator.peek()
        self.assertEqual(entry1_again, (b"key1", b"value1"))
        
        # Now advance
        iterator.next()
        
        # Peek at next entry
        entry2 = iterator.peek()
        self.assertEqual(entry2, (b"key2", b"value2"))
    
    def test_empty_memtable(self):
        """Test iterator on empty memtable"""
        empty_memtable = Memtable()
        iterator = MemtableIterator(empty_memtable)
        
        self.assertFalse(iterator.has_next())
        self.assertIsNone(iterator.peek())
        self.assertIsNone(iterator.next())


def run_tests():
    """Run all Memtable tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestMemtable))
    suite.addTests(loader.loadTestsFromTestCase(TestMemtableIterator))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
