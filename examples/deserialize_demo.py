"""
Demo: Hiểu rõ WAL Deserialize

File này giải thích chi tiết cách deserialize() hoạt động
với ví dụ cụ thể và visualization.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from wal import WALEntry
import struct
from binascii import crc32


def visualize_binary_data(data: bytes, label: str = "Data"):
    """In binary data dưới dạng hex để dễ đọc"""
    print(f"\n{'='*70}")
    print(f"{label} ({len(data)} bytes)")
    print(f"{'='*70}")
    
    # Print hex
    hex_str = data.hex()
    for i in range(0, len(hex_str), 32):
        offset = i // 2
        chunk = hex_str[i:i+32]
        # Format: 2 characters per byte, space every 2 chars
        formatted = ' '.join(chunk[j:j+2] for j in range(0, len(chunk), 2))
        print(f"{offset:04d}: {formatted}")
    print()


def demo_serialize_deserialize():
    """Demo 1: Serialize và Deserialize một entry đơn giản"""
    
    print("\n" + "🎯 DEMO 1: SERIALIZE & DESERIALIZE".center(70, "="))
    
    # ═══════════════════════════════════════════════════════════
    # Bước 1: Tạo WALEntry
    # ═══════════════════════════════════════════════════════════
    key = b"user"
    value = b"alice"
    
    print(f"\n📝 Creating WALEntry:")
    print(f"   Key:   {key!r} ({len(key)} bytes)")
    print(f"   Value: {value!r} ({len(value)} bytes)")
    
    entry = WALEntry(key, value)
    
    
    # ═══════════════════════════════════════════════════════════
    # Bước 2: Serialize
    # ═══════════════════════════════════════════════════════════
    serialized = entry.serialize()
    
    print(f"\n🔧 Serialized to {len(serialized)} bytes:")
    
    # Phân tích từng phần
    print(f"\n   Structure:")
    print(f"   ┌─────────────────────────────────────────────────────┐")
    print(f"   │ [Header: 16B] [Key: 4B] [Value: 5B] [Checksum: 4B] │")
    print(f"   └─────────────────────────────────────────────────────┘")
    print(f"    0              16        20         25            29")
    
    # Header (16 bytes)
    header = serialized[0:16]
    timestamp, key_size, value_size = struct.unpack('<QII', header)
    print(f"\n   Header [0:16]:")
    print(f"      Timestamp:  {timestamp} (8 bytes)")
    print(f"      Key size:   {key_size} (4 bytes)")
    print(f"      Value size: {value_size} (4 bytes)")
    
    # Key (4 bytes)
    key_data = serialized[16:20]
    print(f"\n   Key [16:20]:    {key_data!r}")
    
    # Value (5 bytes)
    value_data = serialized[20:25]
    print(f"   Value [20:25]:  {value_data!r}")
    
    # Checksum (4 bytes)
    checksum_bytes = serialized[25:29]
    checksum = struct.unpack('<I', checksum_bytes)[0]
    print(f"   Checksum [25:29]: {checksum:#010x}")
    
    visualize_binary_data(serialized, "Complete Binary Data")
    
    
    # ═══════════════════════════════════════════════════════════
    # Bước 3: Deserialize
    # ═══════════════════════════════════════════════════════════
    print(f"\n{'='*70}")
    print("🔍 DESERIALIZING (Step by Step)")
    print(f"{'='*70}")
    
    print("\n➤ BƯỚC 1: Đọc Header (16 bytes)")
    print(f"   Offset: 0 → 16")
    offset = 0
    header_data = serialized[offset:offset+16]
    ts, ks, vs = struct.unpack('<QII', header_data)
    print(f"   ✓ Timestamp: {ts}")
    print(f"   ✓ Key size:  {ks}")
    print(f"   ✓ Value size: {vs}")
    offset += 16
    
    print(f"\n➤ BƯỚC 2: Đọc Key ({ks} bytes)")
    print(f"   Offset: {offset-16} → {offset} → {offset+ks}")
    key_recovered = serialized[offset:offset+ks]
    print(f"   ✓ Key: {key_recovered!r}")
    offset += ks
    
    print(f"\n➤ BƯỚC 3: Đọc Value ({vs} bytes)")
    print(f"   Offset: {offset-ks} → {offset} → {offset+vs}")
    is_tombstone = (vs == 0xFFFFFFFF)
    if is_tombstone:
        value_recovered = None
        actual_value_size = 0
        print(f"   💀 TOMBSTONE detected (no value)")
    else:
        value_recovered = serialized[offset:offset+vs]
        actual_value_size = vs
        print(f"   ✓ Value: {value_recovered!r}")
    offset += actual_value_size
    
    print(f"\n➤ BƯỚC 4: Đọc Checksum (4 bytes)")
    print(f"   Offset: {offset-actual_value_size} → {offset} → {offset+4}")
    stored_checksum = struct.unpack('<I', serialized[offset:offset+4])[0]
    print(f"   ✓ Stored checksum: {stored_checksum:#010x}")
    offset += 4
    
    print(f"\n➤ BƯỚC 5: Verify Checksum")
    entry_data_end = offset - 4
    entry_data_start = 0
    data_to_verify = serialized[entry_data_start:entry_data_end]
    print(f"   Calculating checksum of bytes [{entry_data_start}:{entry_data_end}]")
    calculated = crc32(data_to_verify) & 0xFFFFFFFF
    print(f"   ✓ Calculated checksum: {calculated:#010x}")
    
    if stored_checksum == calculated:
        print(f"   ✅ Checksum MATCH - Data is valid!")
    else:
        print(f"   ❌ Checksum MISMATCH - Data corrupted!")
    
    # Now use actual deserialize
    print(f"\n{'='*70}")
    print("✨ USING ACTUAL deserialize() method")
    print(f"{'='*70}")
    
    recovered_entry, next_offset = WALEntry.deserialize(serialized, 0)
    
    print(f"\n✓ Recovered Entry:")
    print(f"   Key:       {recovered_entry.key!r}")
    print(f"   Value:     {recovered_entry.value!r}")
    print(f"   Timestamp: {recovered_entry.timestamp}")
    print(f"   Tombstone: {recovered_entry.is_tombstone}")
    print(f"\n✓ Next offset: {next_offset} (position for next entry)")


def demo_multiple_entries():
    """Demo 2: Deserialize nhiều entries liên tiếp"""
    
    print("\n\n" + "🎯 DEMO 2: MULTIPLE ENTRIES".center(70, "="))
    
    # Tạo 3 entries
    entries = [
        WALEntry(b"key1", b"value1"),
        WALEntry(b"key2", b"value2"),
        WALEntry(b"key3", None),  # DELETE (tombstone)
    ]
    
    # Serialize all
    data = b''.join(e.serialize() for e in entries)
    
    print(f"\n📦 Created 3 entries, total {len(data)} bytes:")
    print(f"   Entry 1: PUT key1=value1")
    print(f"   Entry 2: PUT key2=value2")
    print(f"   Entry 3: DELETE key3")
    
    visualize_binary_data(data[:60], "First 60 bytes")
    
    # Deserialize one by one
    print(f"\n{'='*70}")
    print("🔍 DESERIALIZING SEQUENTIALLY")
    print(f"{'='*70}")
    
    offset = 0
    count = 1
    
    while offset < len(data):
        print(f"\n➤ Entry {count} (starting at offset {offset}):")
        
        try:
            entry, next_offset = WALEntry.deserialize(data, offset)
            
            print(f"   Key:   {entry.key!r}")
            if entry.is_tombstone:
                print(f"   Value: <TOMBSTONE> (deleted)")
            else:
                print(f"   Value: {entry.value!r}")
            
            bytes_read = next_offset - offset
            print(f"   📏 Size: {bytes_read} bytes")
            print(f"   📍 Next offset: {next_offset}")
            
            offset = next_offset
            count += 1
            
        except ValueError as e:
            print(f"   ❌ Error: {e}")
            break
    
    print(f"\n✅ Successfully deserialized {count-1} entries!")


def demo_corrupted_data():
    """Demo 3: Xử lý data bị corrupt"""
    
    print("\n\n" + "🎯 DEMO 3: CORRUPTED DATA DETECTION".center(70, "="))
    
    # Tạo entry hợp lệ
    entry = WALEntry(b"test", b"data")
    serialized = entry.serialize()
    
    print(f"\n📝 Original entry:")
    print(f"   Key:   {entry.key!r}")
    print(f"   Value: {entry.value!r}")
    
    # Corrupt data
    corrupted = bytearray(serialized)
    corrupted[20] ^= 0xFF  # Flip all bits at position 20
    
    print(f"\n🔧 Corrupting byte at position 20:")
    print(f"   Original: {serialized[20]:02x}")
    print(f"   Corrupted: {corrupted[20]:02x}")
    
    # Try to deserialize
    print(f"\n🔍 Attempting to deserialize corrupted data:")
    
    try:
        recovered, _ = WALEntry.deserialize(bytes(corrupted), 0)
        print(f"   ❌ ERROR: Should have detected corruption!")
    except ValueError as e:
        print(f"   ✅ SUCCESS: Corruption detected!")
        print(f"   Error: {e}")


def demo_tombstone():
    """Demo 4: Tombstone (DELETE) entry"""
    
    print("\n\n" + "🎯 DEMO 4: TOMBSTONE (DELETE) ENTRY".center(70, "="))
    
    # Tạo DELETE entry
    key = b"deleted_key"
    entry = WALEntry(key, None)  # None = tombstone
    
    print(f"\n📝 Creating DELETE entry:")
    print(f"   Key:       {key!r}")
    print(f"   Value:     None (tombstone)")
    print(f"   Tombstone: {entry.is_tombstone}")
    
    # Serialize
    serialized = entry.serialize()
    
    print(f"\n🔧 Serialized structure:")
    
    # Parse header
    timestamp, key_size, value_size = struct.unpack('<QII', serialized[0:16])
    
    print(f"   Header:")
    print(f"      Timestamp:  {timestamp}")
    print(f"      Key size:   {key_size}")
    print(f"      Value size: {value_size:#x} (= TOMBSTONE_MARKER)")
    
    print(f"\n   ⚠️  Value size = 0xFFFFFFFF means DELETE!")
    print(f"   ⚠️  No value bytes stored (saves space)")
    
    print(f"\n   Total size: {len(serialized)} bytes")
    print(f"   = 16 (header) + {key_size} (key) + 0 (no value) + 4 (checksum)")
    
    # Deserialize
    print(f"\n🔍 Deserializing:")
    
    recovered, _ = WALEntry.deserialize(serialized, 0)
    
    print(f"   Key:       {recovered.key!r}")
    print(f"   Value:     {recovered.value}")
    print(f"   Tombstone: {recovered.is_tombstone}")
    
    if recovered.is_tombstone:
        print(f"\n   ✅ Correctly identified as DELETE operation!")


if __name__ == '__main__':
    print("\n" + "="*70)
    print("WAL DESERIALIZE DEMO - Chi tiết từng bước".center(70))
    print("="*70)
    
    # Run all demos
    demo_serialize_deserialize()
    demo_multiple_entries()
    demo_corrupted_data()
    demo_tombstone()
    
    print("\n" + "="*70)
    print("✅ ALL DEMOS COMPLETED".center(70))
    print("="*70)
    print("\nĐể hiểu sâu hơn, uncomment các dòng debug trong wal.py")
    print("(tìm dòng có # print(...) trong hàm deserialize)")
    print()
