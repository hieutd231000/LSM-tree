# 🎓 Hướng Dẫn Hiểu `deserialize()` - Giải Thích Chi Tiết

## 🎯 Mục Đích

Hàm `deserialize()` làm ngược lại với `serialize()`:
- **Serialize**: Python object → Binary bytes
- **Deserialize**: Binary bytes → Python object

---

## 📊 Visualize Quá Trình

### Input: Binary Data
```
File WAL chứa binary data liên tục:

┌────────────────────────────────────────────────────────────────┐
│ Entry 1                  │ Entry 2                  │ Entry 3  │
│ [Header][Key][Val][CRC]  │ [Header][Key][Val][CRC]  │ ...      │
└────────────────────────────────────────────────────────────────┘
  ↑                        ↑                          ↑
  offset=0                 offset=29                  offset=59
```

### Deserialize 1 Entry

```
BINARY DATA (29 bytes):
┌──────────────────────────────────────────────────────────────────┐
│ d5 5c 8a 40 23 47 06 00 │ 04 00 00 00 │ 05 00 00 00 │          │
│     Timestamp (8B)       │ KeySz (4B)  │ ValSz (4B)  │          │
├──────────────────────────┴─────────────┴─────────────┤          │
│                     HEADER (16 bytes)                 │          │
└───────────────────────────────────────────────────────┘          │
                                                                   │
┌───────────────────────────────────────────────────────────────┐ │
│ 75 73 65 72 │ 61 6c 69 63 65 │ 15 55 12 1a │                 │ │
│ "user" (4B) │ "alice" (5B)   │ CRC32 (4B)  │                 │ │
├─────────────┴────────────────┴─────────────┘                 │ │
│           DATA + CHECKSUM                                     │ │
└───────────────────────────────────────────────────────────────┘ │
                                                                   │
Total: 16 + 4 + 5 + 4 = 29 bytes                                  │
└───────────────────────────────────────────────────────────────┘
```

---

## 🔍 Step-by-Step Process

### BƯỚC 1: Đọc Header (16 bytes)

```python
# Code
timestamp, key_size, value_size = struct.unpack('<QII', data[offset:offset+16])
offset += 16

# Giải thích
┌─────────────────────────────────────────────────────────┐
│ Input:  data[0:16] = d5 5c 8a 40 23 47 06 00 ...       │
│                                                          │
│ unpack('<QII'):                                          │
│   '<'  → Little-endian                                   │
│   'Q'  → Read 8 bytes → timestamp = 1767066592500949    │
│   'I'  → Read 4 bytes → key_size = 4                    │
│   'I'  → Read 4 bytes → value_size = 5                  │
│                                                          │
│ Output: timestamp, key_size, value_size                  │
│ offset: 0 → 16                                           │
└─────────────────────────────────────────────────────────┘
```

**Tại sao cần header?**
- Biết size của key/value để đọc đúng số bytes tiếp theo
- Không biết size → không biết đọc bao nhiêu bytes!

---

### BƯỚC 2: Đọc Key

```python
# Code
key = data[offset:offset+key_size]
offset += key_size

# Giải thích
┌─────────────────────────────────────────────────────────┐
│ Input:  data[16:20] (đọc key_size=4 bytes)              │
│         = 75 73 65 72                                    │
│         = "user"                                         │
│                                                          │
│ Output: key = b'user'                                   │
│ offset: 16 → 20                                          │
└─────────────────────────────────────────────────────────┘
```

**Trick quan trọng:**
```python
# SAI:
key = data[16:16+4]  # Fixed position - WRONG!

# ĐÚNG:
key = data[offset:offset+key_size]  # Dynamic - RIGHT!
# Vì offset thay đổi khi đọc nhiều entries
```

---

### BƯỚC 3: Đọc Value (hoặc detect Tombstone)

```python
# Code
is_tombstone = (value_size == 0xFFFFFFFF)

if is_tombstone:
    value = None
    actual_value_size = 0
else:
    value = data[offset:offset+value_size]
    actual_value_size = value_size
    offset += actual_value_size

# Giải thích
┌─────────────────────────────────────────────────────────┐
│ Case 1: PUT (value_size = 5)                            │
│   data[20:25] = 61 6c 69 63 65 = "alice"               │
│   value = b'alice'                                      │
│   offset: 20 → 25                                       │
│                                                          │
│ Case 2: DELETE (value_size = 0xFFFFFFFF)               │
│   value = None (no data to read)                       │
│   offset: 20 → 20 (không tăng)                         │
└─────────────────────────────────────────────────────────┘
```

**Tại sao 0xFFFFFFFF?**
```
0xFFFFFFFF = 4,294,967,295 bytes = 4GB

Real value KHÔNG BAO GIỜ lớn đến vậy
→ Dùng làm magic marker cho DELETE
→ Tiết kiệm space (không cần thêm 1 byte flag)
```

---

### BƯỚC 4: Đọc Checksum

```python
# Code
stored_checksum = struct.unpack('<I', data[offset:offset+4])[0]
offset += 4

# Giải thích
┌─────────────────────────────────────────────────────────┐
│ Input:  data[25:29] = 15 55 12 1a                       │
│                                                          │
│ unpack('<I'):                                            │
│   '<'  → Little-endian                                   │
│   'I'  → Read 4 bytes as uint32                         │
│        → 0x1a125515 (439,653,653)                       │
│                                                          │
│ Output: stored_checksum = 0x1a125515                    │
│ offset: 25 → 29                                          │
└─────────────────────────────────────────────────────────┘
```

---

### BƯỚC 5: Verify Checksum

**ĐÂY LÀ PHẦN KHÓC NHẤT!**

```python
# Code (phần này nhiều người bị confused)
entry_data_end = offset - 4
entry_data_start = offset - 4 - actual_value_size - key_size - 16

calculated_checksum = crc32(data[entry_data_start:entry_data_end]) & 0xFFFFFFFF
```

**Giải thích chi tiết:**

```
Current offset = 29 (vị trí SAU checksum)

Cần tính checksum của phần nào?
→ Của [Header + Key + Value] (KHÔNG bao gồm checksum itself!)

Visualize:
┌────────────────────────────────────────────────────────┐
│ [Header: 16B] [Key: 4B] [Value: 5B] │ [Checksum: 4B] │
└────────────────────────────────────────────────────────┘
  ↑                                    ↑                 ↑
  entry_data_start                     entry_data_end    offset
  = 0                                  = 25              = 29

Tính toán ngược:
  offset = 29
  entry_data_end = offset - 4 = 25 (TRƯỚC checksum)
  
  entry_data_start = offset - 4           (skip checksum)
                            - actual_value_size (skip value)
                            - key_size          (skip key)
                            - 16                (skip header)
                   = 29 - 4 - 5 - 4 - 16
                   = 0

Vậy: data[0:25] là phần cần verify
```

**Tại sao phức tạp vậy?**

```python
# Không thể hardcode:
data[0:25]  # WRONG - chỉ đúng cho entry này

# Phải dynamic:
data[entry_data_start:entry_data_end]  # RIGHT

# Vì:
# - Entry 1: data[0:25]
# - Entry 2: data[30:55]  
# - Entry 3: data[60:80]
# → Mỗi entry có position khác nhau!
```

**So sánh:**

```python
if stored_checksum == calculated_checksum:
    # ✅ Data OK
    return entry
else:
    # ❌ Data corrupt
    raise ValueError("Checksum mismatch!")
```

---

## 🔄 Multiple Entries

Khi có nhiều entries liên tiếp:

```python
offset = 0  # Bắt đầu từ đầu file

while offset < len(data):
    entry, next_offset = deserialize(data, offset)
    print(f"Entry: {entry}")
    offset = next_offset  # Nhảy tới entry tiếp theo
```

**Visualize:**

```
File: [Entry1][Entry2][Entry3]

Lần 1:
  offset = 0
  deserialize(data, 0) → (Entry1, 29)
  offset = 29

Lần 2:
  offset = 29
  deserialize(data, 29) → (Entry2, 59)
  offset = 59

Lần 3:
  offset = 59
  deserialize(data, 59) → (Entry3, 83)
  offset = 83 (end of file)
```

---

## 🎓 Key Takeaways

### 1. **Offset Tracking**
```python
offset = 0
offset += 16  # After header
offset += key_size  # After key
offset += value_size  # After value
offset += 4  # After checksum
# → offset bây giờ = vị trí entry tiếp theo
```

### 2. **Dynamic Size**
```python
# Không biết trước size
# → Phải đọc header trước để biết key_size, value_size
# → Rồi mới đọc key, value với đúng size
```

### 3. **Checksum Position**
```python
# Checksum luôn ở CUỐI entry
# Tính checksum từ ĐẦU entry → TRƯỚC checksum
# (Không bao gồm checksum itself)
```

### 4. **Tombstone Detection**
```python
if value_size == 0xFFFFFFFF:
    # DELETE operation
    # Không đọc value bytes
    value = None
```

---

## 🐛 Common Mistakes

### ❌ Mistake 1: Fixed Position
```python
# WRONG
key = data[16:20]  # Assumes entry always starts at 0

# RIGHT
key = data[offset:offset+key_size]  # Dynamic position
```

### ❌ Mistake 2: Include Checksum in Verification
```python
# WRONG
calculated = crc32(data[0:29])  # Includes checksum itself!

# RIGHT
calculated = crc32(data[0:25])  # Excludes checksum
```

### ❌ Mistake 3: Forget to Update Offset
```python
# WRONG
key = data[offset:offset+key_size]
# offset không tăng → đọc sai vị trí tiếp theo

# RIGHT
key = data[offset:offset+key_size]
offset += key_size  # MUST update!
```

---

## 🚀 Chạy Demo

Để thực hành và hiểu rõ hơn:

```bash
# Run demo
python examples/deserialize_demo.py

# Sẽ show:
# - Binary data visualization
# - Step-by-step deserialize
# - Multiple entries
# - Corruption detection
# - Tombstone handling
```

---

## 💡 Tips Để Debug

1. **Print offset sau mỗi step:**
```python
print(f"After header: offset={offset}")
print(f"After key: offset={offset}")
print(f"After value: offset={offset}")
```

2. **Visualize binary data:**
```python
print(data.hex())  # Print as hex
print(data[0:16].hex())  # Just header
```

3. **Uncomment debug lines trong wal.py:**
```python
# Tìm các dòng:
# print(f"📦 Header: ...")
# print(f"🔑 Key: ...")
# Uncomment để xem chi tiết
```

---

**Hy vọng giờ bạn đã hiểu rõ cách `deserialize()` hoạt động!** 🎉

Có câu hỏi gì cứ hỏi tiếp nhé! 😊
