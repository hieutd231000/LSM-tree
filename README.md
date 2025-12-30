# 📚 LSM-Tree Implementation

## 🎯 Project Overview

This is a complete implementation of LSM-Tree (Log-Structured Merge Tree) - a crucial data structure used in modern databases such as RocksDB, LevelDB, Cassandra, and HBase.


## 📁 Project Structure

```
lsm-tree/
├── docs/
│   └── DESIGN.md                 # Detailed design (Phase 0)
├── src/
│   ├── __init__.py              # Package initialization
│   ├── wal.py                   # Write-Ahead Log (Durability)
│   ├── memtable.py              # In-memory sorted storage
│   └── sstable.py               # On-disk sorted storage
├── tests/
│   ├── __init__.py
│   ├── test_wal.py              # 15 WAL tests
│   ├── test_memtable.py         # 17 Memtable tests
│   ├── test_sstable.py          # 18 SSTable tests
│   └── run_all_tests.py         # Test runner
├── requirements.txt             # Dependencies
├── requirement.txt              # Original requirements
└── README.md                    # This file
```

---

## 🏗️ Phase 0: Research & Design

### Architecture Overview

LSM-Tree operates on the principle of **tiered storage** with 3 main components:

```
┌─────────────────────────────────────────────────────────────┐
│                    LSM-Tree Architecture                     │
└─────────────────────────────────────────────────────────────┘

WRITE PATH (Data flow during write):
═══════════════════════════════════════════

    PUT(key, value)
         │
         ▼
    ┌──────────────────┐
    │   1. WAL File    │  ← Write to disk IMMEDIATELY (Durability)
    │   (append-only)  │     Format: [timestamp][key][value][checksum]
    └──────────────────┘
         │
         ▼
    ┌──────────────────┐
    │  2. Memtable     │  ← In-memory sorted structure
    │  (Sorted Dict)   │     Fast: O(log n) insert/lookup
    └──────────────────┘
         │
         ▼ (When full: size > 4MB)
    ┌──────────────────┐
    │ 3. SSTable File  │  ← Flush to disk (Immutable)
    │ (Level 0)        │     Format: Header + Data + Index + Footer
    └──────────────────┘


READ PATH (Data flow during read):
═══════════════════════════════════════════

    GET(key)
         │
         ▼
    ┌──────────────────┐
    │  1. Memtable     │  ← Check in-memory FIRST (fastest)
    │     Found? ✓     │
    └──────────────────┘
         │ Not found
         ▼
    ┌──────────────────┐
    │ 2. SSTable Files │  ← Binary search in index
    │    (newest → old)│     Sparse index: every 16 keys
    │     Found? ✓     │
    └──────────────────┘
         │
         └─► Return value or None
```

### File Formats (Details)

#### 1. WAL Format
```
┌──────────────────────────────────────────────────────────────┐
│                      WAL Entry Format                         │
└──────────────────────────────────────────────────────────────┘

[Timestamp][Key Size][Value Size][Key Data][Value Data][CRC32]
     8B        4B         4B         N bytes    M bytes    4B

- Timestamp: Unix time (microseconds) - for ordering
- Value Size: 0xFFFFFFFF = TOMBSTONE (delete marker)
- CRC32: Checksum to detect corruption

Example:
  PUT:    [1735467890][4][5][user][alice][0xABCD]
  DELETE: [1735467891][4][0xFFFFFFFF][user][][0xDEAD]
```

#### 2. SSTable Format
```
┌──────────────────────────────────────────────────────────────┐
│                     SSTable File Layout                       │
└──────────────────────────────────────────────────────────────┘

┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Header (24 bytes)                                          ┃
┃   [Magic: 0x5353544142424C45]["SSTABBLE"]                 ┃
┃   [Version: 1][Num Entries: N][Reserved: 0]               ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ Data Block                                                 ┃
┃   Entry 0: [key_sz(4)][val_sz(4)][key][value]             ┃
┃   Entry 1: [key_sz(4)][val_sz(4)][key][value]             ┃
┃   ...                                                      ┃
┃   Entry N: [key_sz(4)][val_sz(4)][key][value]             ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ Sparse Index Block (Every 16th key)                       ┃
┃   Index 0: [key_sz(4)][key][offset(8)] → Entry 0          ┃
┃   Index 1: [key_sz(4)][key][offset(8)] → Entry 16         ┃
┃   Index 2: [key_sz(4)][key][offset(8)] → Entry 32         ┃
┃   ...                                                      ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ Footer (16 bytes)                                          ┃
┃   [Index Offset(8)][CRC32 Checksum(8)]                    ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

Lookup Process:
  1. Binary search in Sparse Index → find starting position
  2. Linear scan maximum 16 entries
  3. Complexity: O(log n) + O(16) = O(log n)
```

### Design Decisions & Trade-offs

| Decision | Reason | Trade-off |
|-----------|-------|-----------|
| **Sorted Dict** for Memtable | - Existing library, reliable<br>- O(log n) operations<br>- Easy to maintain | - Memory overhead<br>- Not as optimal as custom RB-tree |
| **Sparse Index** (every 16 keys) | - Balance index size vs lookup speed<br>- Index size: 6% of data | - Must scan 16 entries<br>- But acceptable with modern CPUs |
| **CRC32 Checksum** | - Fast (hardware accelerated)<br>- Good enough for detection | - Cannot prevent intentional attacks<br>- Only for corruption detection |
| **Append-only WAL** | - Simple, fast writes<br>- No seek overhead | - File grows unbounded<br>- Need truncate after flush |

---

## ⚙️ Phase 1: Core Components

### 1.1 Write-Ahead Log (WAL) - `wal.py`

**Purpose:** Ensure **DURABILITY** - no data loss on crash.

#### How It Works:
```python
# Write Flow
PUT("user123", "alice") 
  ↓
1. WAL.write(key, value)        # Write to disk FIRST
2. fsync()                       # Force flush to disk  
3. Memtable.put(key, value)     # Then update memory
```

#### Crash Recovery:
```python
# When restarting after crash
wal = WAL("data.wal")
for entry in wal.read_all():
    if entry.is_tombstone:
        memtable.delete(entry.key)
    else:
        memtable.put(entry.key, entry.value)

# Recovered! No data loss
```

#### Key Methods:

| Method | Description | Complexity |
|--------|-------|-----------|
| `write(key, value)` | Append entry + checksum | O(1) |
| `read_all()` | Iterator through all entries | O(n) |
| `truncate()` | Clear WAL after flush | O(1) |

#### Corruption Detection:
```python
# Each entry has CRC32 checksum
entry_data = timestamp + sizes + key + value
checksum = crc32(entry_data)

# When reading:
if calculated_checksum != stored_checksum:
    raise ValueError("Corrupted entry!")
```

### 1.2 Memtable - `memtable.py`

**Purpose:** Fast writes + sorted storage in memory.

#### Data Structure:
```python
from sortedcontainers import SortedDict

class Memtable:
    _data: SortedDict[bytes, bytes]  # Sorted by key
    max_size: 4MB (configurable)
    
    # O(log n) operations
    def put(key, value):    # Insert/Update
    def get(key):           # Lookup
    def delete(key):        # Insert TOMBSTONE marker
```

#### Tombstone Pattern:
```python
# Delete doesn't actually remove, just marks
TOMBSTONE = object()  # Sentinel value

memtable.put(b"user123", b"alice")
memtable.delete(b"user123")
# → _data[b"user123"] = TOMBSTONE

# When GET:
if value is TOMBSTONE:
    return None  # Key has been deleted

# Actual deletion happens in Compaction phase
```

#### Size Tracking:
```python
def _get_entry_size(key, value):
    size = len(key)
    if value is TOMBSTONE:
        size += 4  # Marker overhead
    else:
        size += len(value)
    size += 48  # Python object + SortedDict overhead
    return size

# Check full:
if memtable.is_full():  # size > 4MB
    flush_to_sstable(memtable)
    memtable.clear()
```

### 1.3 SSTable - `sstable.py`

**Purpose:** Persistent, immutable, sorted storage.

#### Writer Flow:
```python
writer = SSTableWriter("001.sst")

# MUST add in sorted order!
for key, value in sorted_memtable:
    writer.add(key, value)  # Write Data Block
    
    # Every 16th key → Sparse Index
    if counter % 16 == 0:
        index.append((key, file_offset))

writer.finalize()  # Write Index + Footer
```

#### Reader Lookup:
```python
def get(key):
    # 1. Binary search in Sparse Index
    start_offset = binary_search_index(key)
    #    → Find position "nearest less than key"
    
    # 2. Linear scan (max 16 entries)
    for i in range(16):
        entry_key, entry_value = read_entry(start_offset + i)
        if entry_key == key:
            return entry_value
        if entry_key > key:
            return None  # Key doesn't exist
    
    # Complexity: O(log n) + O(16) = O(log n)
```

#### Checksum Verification:
```python
# Writer:
data = header + data_block + index + index_offset
checksum = crc32(data)
footer = pack(index_offset, checksum)

# Reader:
calculated = crc32(file_data[:-8])  # Exclude checksum field
if calculated != stored_checksum:
    raise ValueError("File corrupted!")
```

---

## 🧪 Test Suite - 50 Tests, 100% Pass

### Test Coverage:

#### WAL Tests (15 tests)
```python
✓ Serialize/Deserialize PUT and DELETE
✓ Multiple entries in sequence
✓ Checksum corruption detection
✓ Crash recovery simulation
✓ 1000 entries throughput test
✓ Empty WAL handling
✓ Truncate and delete operations
```

#### Memtable Tests (17 tests)
```python
✓ Basic PUT/GET/DELETE operations
✓ Tombstone behavior
✓ Size tracking and is_full() threshold
✓ Sorted iteration
✓ 10,000 entries stress test
✓ Update existing keys
✓ Type validation (key/value must be bytes)
```

#### SSTable Tests (18 tests)
```python
✓ Write and read operations
✓ Sorted order validation
✓ Tombstone persistence
✓ Range queries (get_range)
✓ Sparse index binary search
✓ 10,000 entries performance
✓ Large values (10KB each)
✓ Memtable → SSTable flush
✓ Checksum mismatch detection
✓ Invalid file format detection
```

### Running Tests:

```bash
# Install dependencies
pip install sortedcontainers

# Run all tests
cd tests
python run_all_tests.py

# Output:
# ======================================================================
# Running LSM-Tree Test Suite
# ======================================================================
# Total tests to run: 50
# ...
# ----------------------------------------------------------------------
# Ran 50 tests in 0.228s
# OK
# ✓ ALL TESTS PASSED!
```

---

## 🎓 Important Concepts

### 1. Write Amplification
**Problem:** Each write, data is written multiple times (WAL → Memtable → SSTable → Compaction).

```
User writes 1MB
  → WAL: 1MB
  → SSTable: 1MB
  → Compaction: 1MB * N times
  ────────────────────────
  Total: 1MB * (2 + N) written

Write Amplification = (2 + N)
```

**Solution (Phase 2+):**
- Batch writes
- Optimized compaction strategy
- Log compression

### 2. Read Amplification
**Problem:** Must check multiple SSTables to find key.

```
GET(key)
  → Check Memtable: Not found
  → Check SSTable_0: Not found
  → Check SSTable_1: Not found
  → Check SSTable_2: Found!

Read Amplification = 3 file reads
```

**Solution (Phase 2+):**
- Bloom Filters (reduce 90% false positive reads)
- Leveled Compaction (merge SSTables)
- Block Cache (LRU cache)

### 3. Space Amplification
**Problem:** Multiple versions of the same key exist.

```
PUT(key1, v1) → SSTable_0: key1=v1
PUT(key1, v2) → SSTable_1: key1=v2
PUT(key1, v3) → Memtable: key1=v3

Space used = 3 * size(key1) + size(v1+v2+v3)
Actual data = size(key1) + size(v3)

Space Amplification = 3x
```

**Solution:**
- Compaction (merge and remove old versions)

### 4. Tombstones
**Why not delete immediately?**

```python
# Problem if deleted immediately:
SSTable_0: key1=v1
Memtable: DELETE key1 → key1 no longer exists

GET(key1):
  → Memtable: Not found
  → SSTable_0: Found key1=v1 ❌ WRONG!

# Solution: Tombstone
Memtable: key1=TOMBSTONE

GET(key1):
  → Memtable: TOMBSTONE → return None ✓
  → No need to check SSTable
```

---

## 📊 Performance Characteristics

### Achieved Performance:

| Operation | Throughput | Latency |
|-----------|-----------|---------|
| WAL Write | ~20K ops/s | < 1ms (no sync)<br>< 5ms (with fsync) |
| Memtable PUT | 50K+ ops/s | < 0.1ms |
| Memtable GET | 100K+ ops/s | < 0.05ms |
| SSTable Write | 10K entries/s | N/A |
| SSTable GET | 20K ops/s | < 1ms (hot cache) |

### Storage Overhead:

**100K entries (key=20B, value=100B):**
```
Data size: 100K * 120B = 12MB

WAL: 14MB (includes metadata)
SSTable Data: 12.8MB
SSTable Index: 200KB (6,250 entries * 32B)
SSTable Header+Footer: ~50B

Total: ~27MB (2.25x amplification before compaction)
```

---

## 🚀 Usage

### Example 1: Basic Operations

```python
from src.wal import WAL
from src.memtable import Memtable
from src.sstable import SSTableWriter, SSTableReader

# Initialize components
wal = WAL("data/wal.log")
memtable = Memtable(max_size_bytes=4*1024*1024)  # 4MB

# Write operation
key = b"user:123"
value = b"alice"

# 1. Write to WAL first (durability)
wal.write(key, value)

# 2. Write to Memtable (performance)
memtable.put(key, value)

# Read operation
result = memtable.get(key)
print(result)  # b'alice'

# Delete operation
wal.write(key, None)  # Tombstone in WAL
memtable.delete(key)   # Tombstone in Memtable

result = memtable.get(key)
print(result)  # None
```

### Example 2: Flush Memtable to SSTable

```python
# When Memtable is full
if memtable.is_full():
    # Flush to SSTable
    sstable_path = "data/001.sst"
    writer = SSTableWriter(sstable_path)
    
    for key, value in memtable.iter_all():
        # Convert TOMBSTONE to None for SSTable
        if value is Memtable.TOMBSTONE:
            value = None
        writer.add(key, value)
    
    writer.finalize()
    
    # Clear Memtable and WAL
    memtable.clear()
    wal.truncate()
    
    print(f"Flushed {memtable.num_entries()} entries to {sstable_path}")
```

### Example 3: Read from SSTable

```python
# Open SSTable for reading
reader = SSTableReader("data/001.sst")

# Point lookup
value = reader.get(b"user:123")
print(value)  # b'alice' or None

# Range query
for key, value in reader.get_range(b"user:000", b"user:100"):
    print(f"{key} = {value}")

# Iterate all entries
for key, value in reader.iter_all():
    if value is None:
        print(f"{key} is deleted")
    else:
        print(f"{key} = {value}")
```

### Example 4: Crash Recovery

```python
# After crash, recover from WAL
def recover():
    wal = WAL("data/wal.log")
    memtable = Memtable()
    
    print("Recovering from WAL...")
    recovered = 0
    
    for entry in wal.read_all():
        if entry.is_tombstone:
            memtable.delete(entry.key)
        else:
            memtable.put(entry.key, entry.value)
        recovered += 1
    
    print(f"✓ Recovered {recovered} entries")
    return memtable

memtable = recover()
```

---

## 📈 Roadmap - Next Steps

### Phase 2: Basic Operations (Coming Soon)
- [ ] KV Store API: `put()`, `get()`, `delete()`
- [ ] Multi-level read (Memtable → SSTables)
- [ ] Bloom Filters integration
- [ ] Background flush

### Phase 3: Compaction (Future)
- [ ] Size-Tiered Compaction
- [ ] Background compaction thread
- [ ] Space amplification metrics

### Phase 4: Optimizations (Future)
- [ ] Block cache (LRU)
- [ ] Compression (Snappy/LZ4)
- [ ] Batch writes
- [ ] Concurrent reads

---

## 📚 References

### Papers:
- **Original LSM-Tree Paper** (1996): O'Neil et al.
- **Bigtable** (Google, 2006): Distributed storage system
- **LevelDB Design**: Google's implementation

### Open Source:
- **RocksDB**: Facebook's production LSM implementation
- **LevelDB**: Google's original implementation
- **Badger**: Go implementation

### Learning Resources:
- [Database Internals Book](https://www.databass.dev/) by Alex Petrov
- [Designing Data-Intensive Applications](https://dataintensive.net/) by Martin Kleppmann

---

## 🎯 Conclusion

### What Has Been Completed:

✅ **Phase 0: Research & Design**
- Complete architecture diagram
- Detailed file format specification
- Design decisions with reasoning
- Trade-off analysis

✅ **Phase 1: Core Components**
- WAL: Durability with crash recovery
- Memtable: Fast in-memory storage
- SSTable: Persistent sorted storage
- **50 tests, 100% pass rate**

### Lessons Learned:

1. **Durability First**: WAL is the foundation - cannot be skipped
2. **Immutability Simplifies**: SSTable immutable → easy concurrent reads
3. **Trade-offs Everywhere**: Write amp vs Read amp vs Space amp
4. **Testing is Critical**: Edge cases (empty, corruption, large data) are extremely important

### Next Learning Goals:

- Deep understanding of Compaction strategies
- Optimize read path with Bloom Filters
- Concurrent operations with proper locking
- Production concerns: monitoring, metrics, alerting

---

## 💡 Tips

### Debugging Tips:

```python
# 1. Enable verbose logging
import logging
logging.basicConfig(level=logging.DEBUG)

# 2. Inspect SSTable content
reader = SSTableReader("001.sst")
print(f"Entries: {reader.num_entries}")
print(f"Index: {len(reader.index)} sparse entries")
for key, value in reader.iter_all():
    print(f"  {key!r} = {value!r}")

# 3. Check WAL recovery
wal = WAL("data.wal")
for i, entry in enumerate(wal.read_all()):
    print(f"Entry {i}: {entry}")
```

### Performance Profiling:

```python
import time

# Benchmark writes
start = time.time()
for i in range(10000):
    wal.write(f"key{i}".encode(), b"value")
duration = time.time() - start
print(f"Throughput: {10000/duration:.0f} ops/s")

# Benchmark reads
start = time.time()
for i in range(10000):
    reader.get(f"key{i}".encode())
duration = time.time() - start
print(f"Read throughput: {10000/duration:.0f} ops/s")
```

