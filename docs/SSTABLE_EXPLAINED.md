# 🗄️ Hướng Dẫn Hiểu SSTable - Giải Thích Chi Tiết

## 🎯 SSTable Là Gì?

**SSTable** = **S**orted **S**tring **Table** = File trên disk lưu data đã sorted, immutable (không thay đổi).

```
LSM-Tree Hierarchy:
┌──────────────┐
│  Memtable    │ ← RAM, mutable, sorted
│   (4 MB)     │
└──────┬───────┘
       │ flush khi đầy
       ▼
┌──────────────┐
│   SSTable    │ ← Disk, immutable, sorted
│  (4-64 MB)   │
└──────────────┘
```

---

## 📁 File Format Overview

```
SSTable File Structure:
┌─────────────────────────────────────────────────────────────┐
│                         HEADER (24 bytes)                    │
│  Magic(4) | Version(4) | NumEntries(8) | IndexOffset(8)     │
├─────────────────────────────────────────────────────────────┤
│                        DATA BLOCKS                           │
│  Entry 1: [KeySize][ValueSize][Key][Value][Checksum]        │
│  Entry 2: [KeySize][ValueSize][Key][Value][Checksum]        │
│  Entry 3: ...                                                │
│  (sorted by key)                                             │
├─────────────────────────────────────────────────────────────┤
│                      SPARSE INDEX                            │
│  IndexEntry 1: [KeySize][Key][Offset]                       │
│  IndexEntry 2: [KeySize][Key][Offset]                       │
│  (mỗi N entries có 1 index)                                 │
├─────────────────────────────────────────────────────────────┤
│                        FOOTER (8 bytes)                      │
│  Checksum(8) - CRC32 của toàn bộ file                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔍 Chi Tiết Từng Phần

### 1. **HEADER (24 bytes)**

```
┌─────────────────────────────────────────────────────────┐
│ Byte 0-3   │ Byte 4-7  │ Byte 8-15      │ Byte 16-23   │
│ Magic      │ Version   │ NumEntries     │ IndexOffset  │
│ 0x53535442 │ 1         │ 1000           │ 45000        │
└─────────────────────────────────────────────────────────┘

Magic = "SSTB" (0x53535442)
  → Verify đây là SSTable file
  
Version = 1
  → File format version (cho tương lai)
  
NumEntries = số lượng data entries
  → Biết có bao nhiêu key-value pairs
  
IndexOffset = vị trí bắt đầu của Sparse Index
  → Jump trực tiếp đến index, skip data section
```

**Mục đích Header:**
- Validate file format (magic number)
- Biết có bao nhiêu entries
- Jump nhanh đến index để binary search

---

### 2. **DATA BLOCKS**

Mỗi entry có format:

```
┌──────────────────────────────────────────────────────────┐
│ KeySize(4) │ ValueSize(4) │ Key │ Value │ Checksum(4)   │
└──────────────────────────────────────────────────────────┘
       ↓            ↓           ↓      ↓         ↓
     uint32      uint32      bytes   bytes    CRC32

Ví dụ cụ thể:
Entry: key=b"user:123", value=b"alice"

Binary:
┌────────────┬─────────────┬──────────────┬─────────┬──────────┐
│ 08 00 00 00│ 05 00 00 00 │ user:123     │ alice   │ xx xx xx │
│ (size=8)   │ (size=5)    │ (8 bytes)    │(5 bytes)│ (4 bytes)│
└────────────┴─────────────┴──────────────┴─────────┴──────────┘
Total: 4 + 4 + 8 + 5 + 4 = 25 bytes
```

**Tombstone trong SSTable:**
```
DELETE entry: key=b"user:456", value=None

Binary:
┌────────────┬─────────────┬──────────────┬──────────┐
│ 08 00 00 00│ FF FF FF FF │ user:456     │ xx xx xx │
│ (size=8)   │ (TOMBSTONE) │ (8 bytes)    │(checksum)│
└────────────┴─────────────┴──────────────┴──────────┘
Total: 4 + 4 + 8 + 4 = 20 bytes (NO value data)
```

**Quan trọng:** Entries được lưu theo thứ tự sorted! 
```
Memtable flush → iter_all() → sorted order → write SSTable
```

---

### 3. **SPARSE INDEX**

**Sparse** = Thưa, không index mọi key, chỉ index mỗi N keys.

```python
INDEX_INTERVAL = 100  # Mỗi 100 entries → 1 index entry

Ví dụ có 1000 entries:
┌─────────────────────────────────────────────────────┐
│ Entry 0:   key=b"a001" → offset=24                  │
│ Entry 1:   key=b"a002" → offset=50                  │
│ ...                                                  │
│ Entry 100: key=b"b020" → offset=2500  ← INDEX #1   │
│ Entry 101: key=b"b021" → offset=2526               │
│ ...                                                  │
│ Entry 200: key=b"c045" → offset=5000  ← INDEX #2   │
│ ...                                                  │
│ Entry 900: key=b"z999" → offset=22500 ← INDEX #9   │
└─────────────────────────────────────────────────────┘

Sparse Index chỉ lưu:
┌──────────────────────────────────────────┐
│ Index #0:  b"a001" → offset=24           │
│ Index #1:  b"b020" → offset=2500         │
│ Index #2:  b"c045" → offset=5000         │
│ Index #3:  b"d070" → offset=7500         │
│ ...                                       │
│ Index #9:  b"z999" → offset=22500        │
└──────────────────────────────────────────┘
10 index entries thay vì 1000!
```

**Index Entry Format:**
```
┌────────────────────────────────────────┐
│ KeySize(4) │ Key │ Offset(8)           │
└────────────────────────────────────────┘

Ví dụ:
┌────────────┬──────────┬─────────────────┐
│ 04 00 00 00│ b020     │ c4 09 00 00 ... │
│ (size=4)   │ (4 bytes)│ (offset=2500)   │
└────────────┴──────────┴─────────────────┘
Total: 4 + 4 + 8 = 16 bytes
```

**Tại sao Sparse?**
- 1000 entries, full index = 16KB
- 1000 entries, sparse index = 160 bytes (10 entries)
- **Tiết kiệm RAM** khi load index vào memory
- Trade-off: Phải scan tối đa 100 entries (linear) sau binary search

---

### 4. **FOOTER (8 bytes)**

```
┌───────────────────────────────────┐
│ File Checksum (8 bytes, CRC32)   │
│ Verify toàn bộ file               │
└───────────────────────────────────┘

Tính checksum:
1. Read toàn bộ file TRỪ 8 bytes cuối
2. CRC32(data) → 4 bytes
3. Pad thành 8 bytes: checksum + (0,0,0,0)
```

---

## ✍️ SSTableWriter - Ghi File

### Flow Ghi SSTable

```python
# 1. Create writer
writer = SSTableWriter("data/sstable_001.sst")

# 2. Add entries (PHẢI sorted order!)
for key, value in memtable.iter_all():
    writer.add(key, value)  # Memtable đã sorted

# 3. Finalize (write index + footer)
writer.finalize()
```

### Chi Tiết `add()` Method

```python
def add(self, key: bytes, value: Optional[bytes]):
    # 1. Check sorted order
    if self._last_key and key <= self._last_key:
        raise ValueError("Keys must be added in sorted order")
    
    # 2. Record offset for sparse index
    current_offset = self._file.tell()  # Vị trí hiện tại
    
    # 3. Write entry
    self._write_entry(key, value)
    
    # 4. Sparse index: mỗi INDEX_INTERVAL entries
    if self._num_entries % INDEX_INTERVAL == 0:
        self._index.append((key, current_offset))
    
    # 5. Update state
    self._last_key = key
    self._num_entries += 1
```

**Ví dụ:**
```python
# Entry 0
add(b"a001", b"val1")
→ offset=24 → INDEX #0: (b"a001", 24)

# Entry 1-99
add(b"a002", ...) → no index
...

# Entry 100
add(b"b020", b"val100")
→ offset=2500 → INDEX #1: (b"b020", 2500)
```

### Chi Tiết `finalize()` Method

```python
def finalize(self):
    # 1. Record index offset
    index_offset = self._file.tell()  # Vị trí sau data blocks
    
    # 2. Write sparse index
    for key, offset in self._index:
        self._write_index_entry(key, offset)
    
    # 3. Go back to start, write header
    self._file.seek(0)
    self._write_header(num_entries, index_offset)
    
    # 4. Calculate file checksum
    self._file.seek(0)
    data = self._file.read()  # All data except footer
    checksum = crc32(data)
    
    # 5. Write footer
    self._file.seek(0, 2)  # End of file
    self._write_footer(checksum)
    
    # 6. Close file
    self._file.close()
```

**Visualize:**
```
Step 1: Write data
┌────────────────────────────────┐
│ [Placeholder Header 24 bytes]  │ ← Bỏ trống, ghi sau
│ Entry 1                        │
│ Entry 2                        │
│ ...                            │
└────────────────────────────────┘

Step 2: Write index
┌────────────────────────────────┐
│ [Placeholder Header]           │
│ Data blocks...                 │
│ Index entry 1                  │ ← Ghi index
│ Index entry 2                  │
└────────────────────────────────┘

Step 3: Write header
┌────────────────────────────────┐
│ ✓ Header (num_entries, offset) │ ← Fill header
│ Data blocks...                 │
│ Index...                       │
└────────────────────────────────┘

Step 4: Write footer
┌────────────────────────────────┐
│ Header                         │
│ Data blocks...                 │
│ Index...                       │
│ ✓ Footer (checksum)            │ ← Ghi checksum
└────────────────────────────────┘
```

---

## 📖 SSTableReader - Đọc File

### Flow Đọc SSTable

```python
# 1. Open reader
reader = SSTableReader("data/sstable_001.sst")

# 2. Get value
value = reader.get(b"user:123")
# → b"alice" hoặc None

# 3. Close
reader.close()
```

### Chi Tiết `__init__()` - Load Index

```python
def __init__(self, filepath):
    self._file = open(filepath, 'rb')
    
    # 1. Read header
    header = self._file.read(24)
    magic, version, num_entries, index_offset = unpack(...)
    
    # 2. Validate magic
    if magic != 0x53535442:  # "SSTB"
        raise ValueError("Invalid SSTable file")
    
    # 3. Jump to index
    self._file.seek(index_offset)
    
    # 4. Read all index entries (vào RAM)
    self._index = []
    while tell() < filesize - 8:  # Before footer
        key, offset = self._read_index_entry()
        self._index.append((key, offset))
    
    # → Index bây giờ trong RAM, ready for binary search!
```

**Index trong RAM:**
```python
_index = [
    (b"a001", 24),
    (b"b020", 2500),
    (b"c045", 5000),
    (b"d070", 7500),
    ...
]
```

---

### Chi Tiết `get(key)` - Binary Search + Linear Scan

Đây là phần **QUAN TRỌNG NHẤT**!

```python
def get(self, key: bytes) -> Optional[bytes]:
    # STEP 1: Binary search trong sparse index
    scan_start_offset = self._find_scan_start(key)
    
    # STEP 2: Linear scan từ offset tìm được
    self._file.seek(scan_start_offset)
    
    while True:
        try:
            entry_key, entry_value = self._read_entry()
            
            if entry_key == key:
                # FOUND!
                if is_tombstone(entry_value):
                    return None  # Deleted
                return entry_value
            
            if entry_key > key:
                # Đã quá key cần tìm (vì sorted)
                return None  # Not found
                
        except EOF:
            return None  # End of file
```

#### STEP 1: Binary Search - `_find_scan_start()`

```python
def _find_scan_start(self, key: bytes) -> int:
    # Binary search trong index để tìm entry <= key
    
    left, right = 0, len(self._index) - 1
    result_offset = 24  # Default: start of data
    
    while left <= right:
        mid = (left + right) // 2
        index_key, index_offset = self._index[mid]
        
        if index_key <= key:
            result_offset = index_offset
            left = mid + 1  # Tìm entry gần hơn
        else:
            right = mid - 1
    
    return result_offset
```

**Ví dụ Binary Search:**

```
Tìm key = b"b500"

Index:
┌─────────────────────────────────────────┐
│ [0] b"a001" → 24                        │
│ [1] b"b020" → 2500    ← Largest <= b"b500"
│ [2] b"c045" → 5000                      │
│ [3] b"d070" → 7500                      │
└─────────────────────────────────────────┘

Binary Search:
  mid=1: b"b020" <= b"b500" ✓
    → result_offset = 2500
    → left = 2
  
  mid=2: b"c045" > b"b500" ✗
    → right = 1
  
  left > right → STOP
  
Return: offset = 2500 (start scan từ b"b020")
```

#### STEP 2: Linear Scan

```
Start từ offset=2500 (b"b020"), scan tuần tự:

┌─────────────────────────────────────────┐
│ offset=2500: b"b020" < b"b500" → skip   │
│ offset=2526: b"b021" < b"b500" → skip   │
│ offset=2552: b"b022" < b"b500" → skip   │
│ ...                                      │
│ offset=3800: b"b500" == b"b500" → FOUND!│
└─────────────────────────────────────────┘
Return value

Hoặc:
┌─────────────────────────────────────────┐
│ offset=2500: b"b020" < b"b500" → skip   │
│ ...                                      │
│ offset=4500: b"b999" < b"b500" → skip   │
│ offset=5000: b"c045" > b"b500" → STOP!  │
└─────────────────────────────────────────┘
Return None (not found)
```

**Tại sao Linear Scan?**
- Binary search chỉ tìm đến index entry gần nhất
- Phải scan max 100 entries (INDEX_INTERVAL)
- Trade-off: Tiết kiệm RAM (sparse index) ↔ Scan thêm entries

---

## 📊 Performance Characteristics

### Time Complexity

| Operation | Complexity | Explanation |
|-----------|-----------|-------------|
| **Write** | O(1) per entry | Append-only, sequential write |
| **Read** | O(log N + K) | log N = binary search index<br>K = linear scan (≤100) |
| **Space** | O(N/100) | Sparse index, 1% of full index |

### Example với 1,000,000 entries

```
Full Index:
  - 1,000,000 index entries
  - ~16 MB RAM
  - Binary search: log₂(1M) ≈ 20 comparisons

Sparse Index (interval=100):
  - 10,000 index entries
  - ~160 KB RAM (100x nhỏ hơn!)
  - Binary search: log₂(10K) ≈ 13 comparisons
  - Linear scan: max 100 entries (nhanh vì sequential read)
  
Total: 13 + 100 = 113 operations
Still very fast!
```

---

## 🎓 Key Takeaways

### 1. **Immutable**
```python
# ✓ ĐÚNG
writer.add(b"key1", b"val1")
writer.finalize()
# File không thay đổi nữa

# ✗ SAI - Không thể update
# SSTable không có update operation!
```

### 2. **Sorted Order**
```python
# ✓ ĐÚNG
writer.add(b"a", ...)
writer.add(b"b", ...)
writer.add(b"c", ...)

# ✗ SAI
writer.add(b"c", ...)
writer.add(b"a", ...)  # ValueError: must be sorted!
```

### 3. **Sparse Index Trade-off**
```
Dense Index:
  + Faster lookup (pure binary search)
  - More RAM

Sparse Index:
  + Less RAM (100x smaller)
  - Slightly slower (add linear scan)
  ✓ Better for LSM-tree (many SSTables)
```

### 4. **Tombstone Persistence**
```python
# Memtable
delete(b"key1")  # → TOMBSTONE object

# SSTable
writer.add(b"key1", None)  # → value_size = 0xFFFFFFFF

# Reader
get(b"key1")  # → None (tombstone detected)
```

---

## 🐛 Common Mistakes

### ❌ Mistake 1: Add entries không sorted
```python
# WRONG
writer.add(b"zebra", ...)
writer.add(b"apple", ...)
# → ValueError!

# RIGHT
entries = sorted(entries, key=lambda x: x[0])
for key, value in entries:
    writer.add(key, value)
```

### ❌ Mistake 2: Quên finalize()
```python
# WRONG
writer.add(...)
writer.add(...)
# → File không có header/index/footer, corrupt!

# RIGHT
writer.add(...)
writer.finalize()  # MUST call!
```

### ❌ Mistake 3: Modify file sau khi write
```python
# WRONG
writer.finalize()
# Manually edit file → checksum mismatch!

# RIGHT
# SSTable is immutable, create new file instead
```

### ❌ Mistake 4: Không verify checksum
```python
# WRONG
# Skip checksum verification → corrupted data

# RIGHT
# Reader tự động verify checksum trong __init__
reader = SSTableReader(filepath)  # Throws if corrupt
```

---

## 🔄 Integration với LSM-Tree

```
Write Path:
┌─────────┐
│   WAL   │ ← Durability
└────┬────┘
     ▼
┌─────────┐
│Memtable │ ← Fast writes (RAM)
└────┬────┘
     │ is_full()?
     ▼
┌─────────┐
│SSTable  │ ← Persistent storage (Disk)
└─────────┘

Read Path:
  GET(key)
     ↓
  Check Memtable (RAM) → Found? Return
     ↓ Not found
  Check SSTable 1 (Disk) → Found? Return
     ↓ Not found
  Check SSTable 2 (Disk) → Found? Return
     ↓ Not found
  Return None
```

---

## 💡 Tips Debug SSTable

### 1. **Dump SSTable content**
```python
reader = SSTableReader("file.sst")
for key, value in reader.iter_all():
    print(f"{key!r} → {value!r}")
```

### 2. **Verify file structure**
```python
# Check header
with open("file.sst", "rb") as f:
    magic = struct.unpack("<I", f.read(4))[0]
    print(f"Magic: 0x{magic:08x}")  # Should be 0x53535442
```

### 3. **Inspect hex dump**
```bash
# Linux/Mac
xxd file.sst | head -n 10

# Windows
format-hex file.sst | Select-Object -First 10
```

### 4. **Check file size**
```python
# Estimate: num_entries * avg_entry_size
# Header: 24 bytes
# Footer: 8 bytes
# Index: num_entries/100 * 16 bytes
# Data: num_entries * (avg_key_size + avg_value_size + 12)
```

---

## 🚀 Advanced Topics

### Bloom Filter (Phase 3)
```python
# Tối ưu: Tránh đọc file khi key chắc chắn không tồn tại
if not bloom_filter.might_contain(key):
    return None  # Skip disk read

# Only search if bloom filter says "maybe"
return reader.get(key)
```

### Compaction (Phase 3)
```python
# Merge nhiều SSTables → 1 SSTable mới
# Remove tombstones, deduplicate keys
writer = SSTableWriter("merged.sst")
for key, value in merge_iterator(sstables):
    if value is not TOMBSTONE:
        writer.add(key, value)
writer.finalize()
```

---

**Tóm lại:** SSTable là file immutable, sorted, dùng sparse index + binary search cho read nhanh, là nền tảng của LSM-tree! 🎉
