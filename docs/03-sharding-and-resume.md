# 03. 分片和断点续跑

全量采集的核心是可恢复。

我这次用的是国家分片 + JSONL 追加写。

## 分片方式

先拿到每个国家或地区的大概数据量。

然后用贪心分配：

1. 按数据量从大到小排序。
2. 每次把下一个国家放到当前总量最小的 shard。
3. 生成 `shard_01.txt`、`shard_02.txt`、`shard_03.txt`。

这样每个分片的数据量更接近。

## JSONL 进度

每成功采到一个详情页，就追加一行 JSON。

好处：

- 中断后文件仍然可用。
- resume 时可以跳过已有 `detail_url`。
- 多个分片可以独立推进。
- 合并 CSV 时可以按 `detail_url` 去重。

## 推荐文件

```text
output/
  shards/
    shard_01.txt
    shard_02.txt
    shard_03.txt
  global_full_part_01.jsonl
  global_full_part_02.jsonl
  global_full_part_03.jsonl
  part_01.live.log
  part_02.live.log
  part_03.live.log
```

## 本仓库里的样例工具

```bash
python3 scripts/build_shards.py examples/countries.sample.csv --shards 3 --output-dir /tmp/datacenter-shards
```

