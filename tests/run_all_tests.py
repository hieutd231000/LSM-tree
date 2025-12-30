"""
Run all tests for LSM-Tree implementation

This script runs all test suites and reports results.
"""

import sys
import unittest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# Import test modules
from test_wal import TestWALEntry, TestWAL
from test_memtable import TestMemtable, TestMemtableIterator
from test_sstable import (
    TestSSTableWriter, 
    TestSSTableReader, 
    TestSSTableLarge,
    TestSSTableFromMemtable,
    TestSSTableCorruption
)


def run_all_tests():
    """Run all test suites"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test cases
    print("=" * 70)
    print("Running LSM-Tree Test Suite")
    print("=" * 70)
    print()
    
    # WAL tests
    print("Loading WAL tests...")
    suite.addTests(loader.loadTestsFromTestCase(TestWALEntry))
    suite.addTests(loader.loadTestsFromTestCase(TestWAL))
    
    # Memtable tests
    print("Loading Memtable tests...")
    suite.addTests(loader.loadTestsFromTestCase(TestMemtable))
    suite.addTests(loader.loadTestsFromTestCase(TestMemtableIterator))
    
    # SSTable tests
    print("Loading SSTable tests...")
    suite.addTests(loader.loadTestsFromTestCase(TestSSTableWriter))
    suite.addTests(loader.loadTestsFromTestCase(TestSSTableReader))
    suite.addTests(loader.loadTestsFromTestCase(TestSSTableLarge))
    suite.addTests(loader.loadTestsFromTestCase(TestSSTableFromMemtable))
    suite.addTests(loader.loadTestsFromTestCase(TestSSTableCorruption))
    
    print()
    print("=" * 70)
    print(f"Total tests to run: {suite.countTestCases()}")
    print("=" * 70)
    print()
    
    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print()
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print("=" * 70)
    
    if result.wasSuccessful():
        print("✓ ALL TESTS PASSED!")
        return 0
    else:
        print("✗ SOME TESTS FAILED")
        return 1


if __name__ == '__main__':
    exit_code = run_all_tests()
    sys.exit(exit_code)
