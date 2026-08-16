高质量回答必须识别：

- CacheEntry 是不可变数据对象，包含 value 和 expires_at。
- read_entry 在 now < expires_at 时返回 value。
- now == expires_at 也视为已过期，必须返回 None。
- now > expires_at 同样返回 None。
- 测试覆盖过期前、精确过期时刻和过期后的三种情况。
