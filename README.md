# DataCenterMap Scraper Playbook

DataCenterMap 爬虫 / data center scraper 的一次真实项目复盘。一份长跑采集地图：先跑样例、解析 `window.__NEXT_DATA__`、按国家分片、用 JSONL 断点续跑，再用 watchdog 盯住卡死的分片。

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![Type](https://img.shields.io/badge/type-playbook%20%2B%20templates-blue)

关键词：DataCenterMap scraper、data center crawler、data center dataset、JSONL resume、crawler watchdog、sharded web scraping。

## 🌱 这个 repo 是什么

这个 repo 来自一个 DataCenterMap 信息点采集项目。

我先做了 10 条样例，用来确认字段范围。后面扩到全量时，真正麻烦的地方变成长跑稳定性：

- 页面有结构化数据，优先读 `window.__NEXT_DATA__` 会比纯 DOM 稳很多。
- 全量采集容易跑很久，单进程中断后很难判断进度。
- 国家和地区数据量差异很大，需要按数量做分片。
- 每个分片写自己的 JSONL，随时可以 resume。
- 某一片卡住时，watchdog 要能发现并重启。
- 最后交付要从多个 JSONL 合并成客户能看的 CSV。

我把这次项目里通用的部分抽出来，放成这个 playbook。以后做公开目录站、设施库、企业库、数据中心库这类长跑采集，可以直接参考这里的流程。

## 🚀 先跑一下

这个仓库只有脱敏样例和辅助脚本。

```bash
git clone https://github.com/Ce-Legend/datacentermap-scraper-playbook.git
cd datacentermap-scraper-playbook
```

校验样例 JSONL：

```bash
python3 scripts/validate_jsonl.py examples/datacenters.sample.jsonl
```

把样例 JSONL 合并成 CSV：

```bash
python3 scripts/merge_jsonl_to_csv.py examples/datacenters.sample.jsonl --output /tmp/datacenters.sample.csv
```

按数量生成样例分片：

```bash
python3 scripts/build_shards.py examples/countries.sample.csv --shards 3 --output-dir /tmp/datacenter-shards
```

## 📦 里面有什么

```text
.
├── README.md
├── docs/
│   ├── 01-sample-first.md
│   ├── 02-next-data-parsing.md
│   ├── 03-sharding-and-resume.md
│   ├── 04-watchdog-runbook.md
│   └── 05-delivery-checklist.md
├── examples/
│   ├── countries.sample.csv
│   └── datacenters.sample.jsonl
└── scripts/
    ├── build_shards.py
    ├── merge_jsonl_to_csv.py
    └── validate_jsonl.py
```

## 🧭 我最想留下来的几个经验

### 1. 先跑 10 条样例

这个项目一开始先跑了一个局部市场的 10 条样例。

这个动作很小，但很值。字段范围、CSV 样式、客户想看的内容，都可以先在样例阶段确认。

样例阶段重点看：

- 基础信息够不够。
- 外部官网能不能回查。
- Overview 和 Specs 字段有没有用。
- 坐标、服务标签、生态信息有没有必要保留。
- CSV 是否方便客户直接看。

### 2. 结构化数据优先

DataCenterMap 页面里有前端直接使用的数据。

我优先解析 `window.__NEXT_DATA__`，再把字段整理成稳定结构。

这个选择让后面很多事变简单：

- 字段更完整。
- 布尔值、容量、坐标更干净。
- 页面文案变化对结果影响小。
- 同一套逻辑可以输出 JSONL 和 CSV。

### 3. JSONL 很适合长跑

全量采集时，我没有等所有数据跑完再写文件。

每拿到一个详情页，就追加一行 JSONL。

这样中断也不慌：

- 已写入的数据还在。
- resume 时可以跳过已有 URL。
- 多个分片可以各写各的进度文件。
- 最后再统一合并 CSV。

### 4. 分片比单进程安心

国家和地区的数据量差异很大。直接全量跑一个进程，出了问题很难判断卡在哪里。

我按国家和数据量做了 shard：

- 每个 shard 有自己的输入文件。
- 每个 shard 有自己的 JSONL。
- 每个 shard 有自己的 live log。
- 某一片卡住时，只处理那一片。

长跑任务的关键是可恢复、可观察、可局部修复。

### 5. watchdog 盯的是进度

watchdog 不需要很复杂。

它主要盯几件事：

- 分片进程还在不在。
- JSONL 有没有继续增长。
- live log 有没有继续更新。
- 站点当前是否能打开。
- 卡住时只重启对应分片。

这个思路比盲目定时重启稳很多。

## 🧩 推荐数据结构

样例数据在 [examples/datacenters.sample.jsonl](examples/datacenters.sample.jsonl)。

每行是一条 data center 记录：

```json
{
  "source": {
    "detail_url": "https://www.datacentermap.com/example/sample-dc/"
  },
  "identity": {
    "name": "Sample Data Center",
    "operator_name": "Sample Operator"
  },
  "address": {
    "country": "Sample Country",
    "city": "Sample City"
  },
  "location": {
    "latitude": 51.5,
    "longitude": -0.1
  },
  "overview": {
    "labels": ["Private Cabinets", "Remote Hands"]
  },
  "specs": {
    "capacity": {
      "power_mw": "2.7 MW",
      "whitespace": "1,867 sq.m."
    }
  }
}
```

## ✅ 校验脚本会查什么

[scripts/validate_jsonl.py](scripts/validate_jsonl.py) 会检查：

- JSONL 是否能逐行解析。
- `detail_url` 是否缺失。
- `name` 是否缺失。
- 是否有重复 `detail_url`。
- 国家、城市、坐标、外部官网等核心字段覆盖率。

示例：

```bash
python3 scripts/validate_jsonl.py examples/datacenters.sample.jsonl
```

## 📝 合并脚本会生成什么

[scripts/merge_jsonl_to_csv.py](scripts/merge_jsonl_to_csv.py) 会把一个或多个 JSONL 合成 CSV。

默认输出这些字段：

- name
- operator_name
- country
- city
- address
- latitude
- longitude
- external_website
- services
- power_mw
- whitespace
- detail_url

示例：

```bash
python3 scripts/merge_jsonl_to_csv.py examples/datacenters.sample.jsonl --output /tmp/datacenters.sample.csv
```

## 🙌 参考

- [DataCenterMap](https://www.datacentermap.com/datacenters/)：这次项目的公开数据来源。
- [Playwright](https://playwright.dev/python/)：动态页面读取和连通性检查。
- [JSON Lines](https://jsonlines.org/)：长跑任务的进度文件格式。
- [douyin-comment-crawler-playbook](https://github.com/Ce-Legend/douyin-comment-crawler-playbook)：同一套项目包装风格的第一个示范。

## 📄 License

MIT
