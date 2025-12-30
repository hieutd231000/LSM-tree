# LSM-Tree Design Document

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    LSM-Tree KV Store                         │
└─────────────────────────────────────────────────────────────┘

Write Path:
───────────
PUT(key, value)
     │
     ├──► 1. WAL (Write-Ahead Log) ──► Append to log file
     │                                  [Durability]
     │
     └──► 2. Memtable (In-Memory)  ──► Sorted structure
                  │                     (Red-Black Tree / Skip List)
                  │
                  ▼ (When size > 4MB threshold)
          3. Flush to SSTable
                  │
                  ▼
          ┌──────────────────┐
          │  SSTable Files   │
          │  (Immutable)     │
          │  Level 0: 001.sst│
          │  Level 0: 002.sst│
          │  Level 0: 003.sst│
          └──────────────────┘
                  │
                  ▼ (Compaction)
          ┌──────────────────┐
          │  Merged SSTables │
          │  Level 1: 004.sst│
          └──────────────────┘

Read Path:
──────────
GET(key)
     │
     ├──► 1. Check Memtable (fastest)
     │         │
     │         ├──► Found? Return value
     │         │
     │         └──► Not found?
     │                  │
     └──────────────────┘
                  │
                  ▼
          2. Check SSTables (newest → oldest)
                  │
                  ├──► Bloom Filter (quick negative check)
                  │
                  ├──► Sparse Index (binary search)
                  │
                  └──► Data Block (read value)

Delete Path:
────────────
DELETE(key)
     │
     ├──► 1. WAL (tombstone marker)
     │
     └──► 2. Memtable (insert tombstone)
              │
              ▼ (Compaction removes tombstones)
```

## 2. File Formats

### 2.1 WAL (Write-Ahead Log) Format

**Purpose**: Ensure durability - recover data after crash

```
File: wal.log (append-only)

Entry Format:
┌────────────┬───────────┬─────────────┬─────────┬───────────┬──────────┐
│ Timestamp  │ Key Size  │ Value Size  │   Key   │   Value   │ Checksum │
│  (8 bytes) │ (4 bytes) │  (4 bytes)  │ (N bytes│  (M bytes)│ (4 bytes)│
└────────────┴───────────┴─────────────┴─────────┴───────────┴──────────┘

Fields:
- Timestamp: uint64 (Unix timestamp in microseconds)
- Key Size: uint32 (length of key)
- Value Size: uint32 (length of value, 0xFFFFFFFF for tombstone)
- Key: bytes (actual key data)
- Value: bytes (actual value data, empty for tombstone)
- Checksum: uint32 (CRC32 of timestamp+sizes+key+value)

Example Entry (PUT):
  [1735467890123456][4][11][user]["hello world"][0xABCD1234]

Example Entry (DELETE):
  [1735467890123457][4][0xFFFFFFFF][user][][0xDEADBEEF]
```

### 2.2 SSTable (Sorted String Table) Format

**Purpose**: Persistent, immutable, sorted key-value storage

```
File: 001.sst, 002.sst, ...

Overall Structure:
┌─────────────────────────────────────────────────────┐
│ Header (24 bytes)                                    │
├─────────────────────────────────────────────────────┤
│ Data Block                                           │
│   Entry 1: [key_size][value_size][key][value]       │
│   Entry 2: [key_size][value_size][key][value]       │
│   ...                                                │
│   Entry N: [key_size][value_size][key][value]       │
├─────────────────────────────────────────────────────┤
│ Index Block (Sparse Index)                          │
│   Index Entry 1: [key_size][key][offset]            │
│   Index Entry 2: [key_size][key][offset]            │
│   ... (every 16 entries)                            │
├─────────────────────────────────────────────────────┤
│ Footer (16 bytes)                                    │
└─────────────────────────────────────────────────────┘

Header Format (24 bytes):
┌───────────────┬─────────┬──────────────┬────────────┐
│ Magic Number  │ Version │ Num Entries  │ Min Key Len│
│   (8 bytes)   │ (4 bytes│  (8 bytes)   │  (4 bytes) │
└───────────────┴─────────┴──────────────┴────────────┘

Data Entry Format:
┌───────────┬─────────────┬─────────┬───────────┐
│ Key Size  │ Value Size  │   Key   │   Value   │
│ (4 bytes) │  (4 bytes)  │ (N)     │   (M)     │
└───────────┴─────────────┴─────────┴───────────┘
Note: Value Size = 0xFFFFFFFF indicates tombstone

Index Entry Format:
┌───────────┬─────────┬───────────────┐
│ Key Size  │   Key   │ Data Offset   │
│ (4 bytes) │  (N)    │  (8 bytes)    │
└───────────┴─────────┴───────────────┘

Footer Format (16 bytes):
┌──────────────┬──────────┐
│ Index Offset │ Checksum │
│  (8 bytes)   │ (8 bytes)│
└──────────────┴──────────┘
```

## 3. Data Structures

### 3.1 Memtable

**Choice**: Sorted Dictionary (Python's SortedDict from sortedcontainers)

**Alternatives Considered**:
- Red-Black Tree: O(log n) insert/search, complex to implement
- Skip List: O(log n) probabilistic, simpler than RB-tree
- **SortedDict**: O(log n) operations, built-in, production-ready

**Configuration**:
- Max Size: 4 MB (configurable)
- Flush Trigger: Size threshold
- Thread Safety: Single-threaded for Phase 1

### 3.2 SSTable Index

**Sparse Index**: 
- Index every 16th key (trade-off between index size and search speed)
- Binary search on index → linear scan of 16 entries max

### 3.3 Compaction Strategy

**Phase 1**: Size-Tiered Compaction (Simple)

**Algorithm**:
1. Group SSTables by size buckets (0-10MB, 10-50MB, 50-100MB, ...)
2. When bucket has ≥ 4 SSTables → merge
3. Multi-way merge sort across SSTables
4. Discard:
   - Tombstones (older than threshold)
   - Duplicate keys (keep newest version)
5. Write new SSTable

**Trigger Conditions**:
- SSTable count > 10
- Total size > 100 MB
- Manual trigger

## 4. Capacity Estimation

### Scenario: 100K writes

**Assumptions**:
- Average key size: 20 bytes
- Average value size: 100 bytes
- Overhead per entry: ~20 bytes (sizes, checksum, padding)

**Calculations**:

WAL Size:
```
Entry size = 8 (timestamp) + 4 (key_size) + 4 (val_size) + 20 (key) + 100 (value) + 4 (checksum)
          = 140 bytes per entry
100K entries = 140 * 100,000 = 14 MB
```

SSTable Size (with compression ~50%):
```
Entry size = 4 (key_size) + 4 (val_size) + 20 (key) + 100 (value)
          = 128 bytes per entry
Header = 24 bytes
Index = (100,000 / 16 entries) * (4 + 20 + 8) = 6,250 * 32 = 200 KB
Footer = 16 bytes
Data = 128 * 100,000 = 12.8 MB

Total = 24 + 12.8 MB + 200 KB + 16 = ~13 MB
With compression: ~6.5 MB
```

**Total Disk Usage**: ~20 MB (WAL + SSTable)

### Space Amplification

Without Compaction:
- If Memtable flushes 10 times → 10 SSTables
- Overlapping keys → Space amplification = 2-3x

With Compaction:
- Space amplification = 1.2-1.5x

## 5. Assumptions & Limitations

### Phase 1 Assumptions:
1. **Single-threaded**: No concurrent reads/writes
2. **No compression**: Raw data storage
3. **No Bloom filters**: Check all SSTables
4. **Simple compaction**: Size-tiered only
5. **Max value size**: 1 MB
6. **Max key size**: 1 KB
7. **No transactions**: Single operation atomicity via WAL
8. **No replication**: Single node only

### Known Limitations:
1. **Read Amplification**: May scan multiple SSTables
2. **Write Amplification**: Compaction rewrites data
3. **No range queries**: Only point lookups
4. **No snapshots**: No consistent point-in-time views
5. **Fixed compaction**: No adaptive strategies

## 6. Performance Expectations

### Phase 1 Targets:

| Operation | Throughput | Latency (p99) |
|-----------|-----------|---------------|
| PUT       | 10K ops/s | < 5ms         |
| GET (hot) | 20K ops/s | < 1ms         |
| GET (cold)| 5K ops/s  | < 10ms        |
| DELETE    | 10K ops/s | < 5ms         |

### Bottlenecks:
- **Write**: Disk I/O for WAL sync
- **Read**: SSTable count (before compaction)
- **Compaction**: Disk I/O + CPU for merge sort

## 7. Testing Strategy

### Unit Tests:
- WAL: write, read, recovery, corruption
- Memtable: insert, search, flush, size limits
- SSTable: write, read, binary search, invalid data

### Integration Tests:
- End-to-end: PUT → GET → DELETE
- Crash recovery: Kill during write → recover
- Compaction: Multiple SSTables → verify data integrity

### Performance Tests:
- Sequential writes: 100K entries
- Random reads: 10K queries
- Mixed workload: 50% read, 40% write, 10% delete

## 8. Future Enhancements (Phase 2+)

1. **Bloom Filters**: 90% reduction in false positive reads
2. **Block Cache**: LRU cache for hot data blocks
3. **Compression**: Snappy/LZ4 → 50-70% size reduction
4. **Leveled Compaction**: Better read amplification
5. **Concurrent Operations**: Thread-safe reads/writes
6. **Range Queries**: Scan by key prefix
7. **Batch Operations**: Atomic multi-PUT/DELETE

---

**Document Version**: 1.0  
**Last Updated**: 2025-12-29  
**Author**: Senior SA Implementation
