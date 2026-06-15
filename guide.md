下面是一套**最省事、可长期自动更新**的方案：

> **GitHub Actions 定时拉 Crossref → 生成 RSS XML → GitHub Pages 托管 → RSS 阅读器订阅。**

不需要买服务器。

---

# 一、最终效果

完成后你会得到类似这样的订阅地址：

```text
https://你的GitHub用户名.github.io/journal-rss/nature.xml
https://你的GitHub用户名.github.io/journal-rss/science.xml
```

把这些地址放进 RSS 阅读器，例如 FreshRSS、Miniflux、Inoreader、Feedly，就能订阅期刊最新论文。

这里用 Crossref 数据源。Crossref REST API 支持按 endpoint、filter、sort 等参数查询文献元数据，适合生成期刊论文 RSS。([www.crossref.org][1])

---

# 二、准备工作

你需要：

1. 一个 GitHub 账号。
2. 目标期刊的 ISSN。
3. 一个 RSS 阅读器。

ISSN 可以在期刊官网找到，通常长这样：

```text
1476-4687
0036-8075
0140-6736
```

一个期刊可能有 Print ISSN 和 Online ISSN。优先用 **Online ISSN**；如果查不到结果，再换 Print ISSN。

---

# 三、创建 GitHub 仓库

进入 GitHub，新建一个仓库：

```text
journal-rss
```

建议设置为：

```text
Public
```

创建后，仓库地址大概是：

```text
https://github.com/你的用户名/journal-rss
```

---

# 四、创建目录结构

在仓库里创建以下文件：

```text
journal-rss/
├── journals.yml
├── generate.py
├── requirements.txt
├── docs/
│   └── index.html
└── .github/
    └── workflows/
        └── update.yml
```

其中：

```text
journals.yml
```

用来写你要订阅哪些期刊。

```text
generate.py
```

用来从 Crossref 拉数据并生成 RSS。

```text
docs/
```

用来放最终生成的 RSS 文件。

```text
.github/workflows/update.yml
```

用来让 GitHub 每天自动运行脚本。

GitHub Actions 支持用 `schedule` 事件按 POSIX cron 定时运行工作流。([GitHub Docs][2]) GitHub Pages 可以从指定分支或文件夹发布站点，比如从 `main` 分支的 `/docs` 文件夹发布。([GitHub Docs][3])

---

# 五、写 `journals.yml`

新建文件：

```text
journals.yml
```

内容如下：

```yaml
- name: Nature
  issn: 1476-4687
  slug: nature
  homepage: https://www.nature.com/nature/

- name: Science
  issn: 0036-8075
  slug: science
  homepage: https://www.science.org/journal/science

- name: The Lancet
  issn: 0140-6736
  slug: lancet
  homepage: https://www.thelancet.com/journals/lancet
```

字段解释：

```yaml
name
```

RSS 里显示的期刊名。

```yaml
issn
```

期刊 ISSN。

```yaml
slug
```

最终 RSS 文件名。例如 `nature` 会生成：

```text
nature.xml
```

```yaml
homepage
```

RSS channel 的主页链接。

你之后要加期刊，只需要继续往这个文件里加：

```yaml
- name: Journal Name
  issn: 0000-0000
  slug: journal-name
  homepage: https://example.com
```

---

# 六、写 `requirements.txt`

新建文件：

```text
requirements.txt
```

内容：

```txt
requests
PyYAML
```

---

# 七、写 `generate.py`

新建文件：

```text
generate.py
```

复制下面完整代码：

```python
import os
import re
import time
import yaml
import requests
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape


OUTPUT_DIR = "docs"
ROWS_PER_JOURNAL = 30

# 建议改成你自己的邮箱。Crossref 鼓励清楚标识 API 请求来源。
CONTACT_EMAIL = "your-email@example.com"


def safe_text(value, fallback=""):
    if value is None:
        return fallback
    return str(value)


def normalize_slug(slug):
    slug = slug.lower().strip()
    slug = re.sub(r"[^a-z0-9\-]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def crossref_date_to_datetime(item):
    candidates = [
        item.get("published-online"),
        item.get("published-print"),
        item.get("published"),
        item.get("created"),
        item.get("deposited"),
    ]

    for candidate in candidates:
        if not candidate:
            continue

        date_parts = candidate.get("date-parts")
        if not date_parts or not date_parts[0]:
            continue

        parts = date_parts[0]

        year = parts[0]
        month = parts[1] if len(parts) >= 2 else 1
        day = parts[2] if len(parts) >= 3 else 1

        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            continue

    return datetime.now(timezone.utc)


def get_title(item):
    titles = item.get("title") or []
    if titles:
        return safe_text(titles[0], "Untitled")
    return "Untitled"


def get_authors(item, max_authors=8):
    authors = item.get("author") or []
    names = []

    for author in authors[:max_authors]:
        given = author.get("given", "")
        family = author.get("family", "")
        name = f"{given} {family}".strip()
        if name:
            names.append(name)

    if len(authors) > max_authors:
        names.append("et al.")

    return ", ".join(names)


def get_doi_link(item):
    doi = item.get("DOI")
    if doi:
        return f"https://doi.org/{doi}"
    return item.get("URL", "")


def get_abstract(item):
    abstract = item.get("abstract", "")
    if not abstract:
        return ""

    # Crossref abstract 有时包含简单 JATS/XML 标签，做一个粗略清理
    abstract = re.sub(r"<[^>]+>", " ", abstract)
    abstract = re.sub(r"\s+", " ", abstract).strip()
    return abstract


def build_rss(journal, items):
    journal_name = journal["name"]
    homepage = journal.get("homepage", "")
    now = datetime.now(timezone.utc)

    rss_items = []

    for item in items:
        title = get_title(item)
        link = get_doi_link(item)
        doi = item.get("DOI", link)
        authors = get_authors(item)
        abstract = get_abstract(item)
        pub_dt = crossref_date_to_datetime(item)

        description_parts = []
        if authors:
            description_parts.append(f"Authors: {authors}")
        if abstract:
            description_parts.append(abstract)

        description = "\n\n".join(description_parts)

        rss_items.append(f"""
    <item>
      <title>{escape(title)}</title>
      <link>{escape(link)}</link>
      <guid isPermaLink="false">{escape(doi)}</guid>
      <pubDate>{format_datetime(pub_dt)}</pubDate>
      <description>{escape(description)}</description>
    </item>""")

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{escape(journal_name)} Latest Articles</title>
    <link>{escape(homepage)}</link>
    <description>Latest journal articles for {escape(journal_name)}</description>
    <language>en</language>
    <lastBuildDate>{format_datetime(now)}</lastBuildDate>
{''.join(rss_items)}
  </channel>
</rss>
"""

    return rss


def fetch_crossref_items(issn):
    url = f"https://api.crossref.org/journals/{issn}/works"

    params = {
        "filter": "type:journal-article",
        "sort": "published",
        "order": "desc",
        "rows": ROWS_PER_JOURNAL,
        "mailto": CONTACT_EMAIL,
    }

    headers = {
        "User-Agent": f"journal-rss-generator/1.0 (mailto:{CONTACT_EMAIL})"
    }

    response = requests.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()

    data = response.json()
    return data["message"]["items"]


def write_index(journals):
    links = []

    for journal in journals:
        slug = normalize_slug(journal["slug"])
        name = journal["name"]
        links.append(f'<li><a href="{slug}.xml">{escape(name)}</a></li>')

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Journal RSS Feeds</title>
</head>
<body>
  <h1>Journal RSS Feeds</h1>
  <ul>
    {''.join(links)}
  </ul>
</body>
</html>
"""

    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open("journals.yml", "r", encoding="utf-8") as f:
        journals = yaml.safe_load(f)

    for journal in journals:
        name = journal["name"]
        issn = journal["issn"]
        slug = normalize_slug(journal["slug"])

        print(f"Fetching {name} ({issn})...")

        try:
            items = fetch_crossref_items(issn)
            rss = build_rss(journal, items)

            output_path = os.path.join(OUTPUT_DIR, f"{slug}.xml")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(rss)

            print(f"Generated {output_path}")

            # 避免过快请求
            time.sleep(1)

        except Exception as e:
            print(f"Failed to generate feed for {name}: {e}")

    write_index(journals)


if __name__ == "__main__":
    main()
```

RSS 2.0 的 channel 至少需要 `title`、`link`、`description`，这里的脚本已经生成这些基础字段，并为每篇论文生成 `item`。([RSS 协调委员会][4])

需要改的一处是：

```python
CONTACT_EMAIL = "your-email@example.com"
```

改成你自己的邮箱，例如：

```python
CONTACT_EMAIL = "yxwan8@gmail.com"
```

---

# 八、本地测试

如果你电脑有 Python，可以先本地测试。

在项目目录运行：

```bash
pip install -r requirements.txt
python generate.py
```

运行成功后，会生成：

```text
docs/nature.xml
docs/science.xml
docs/lancet.xml
docs/index.html
```

打开：

```text
docs/index.html
```

可以看到 RSS 列表。

也可以直接打开：

```text
docs/nature.xml
```

如果能看到 XML 内容，说明 RSS 已生成。

---

# 九、写 GitHub Actions 自动更新

创建文件：

```text
.github/workflows/update.yml
```

内容如下：

```yaml
name: Update journal RSS feeds

on:
  schedule:
    - cron: "15 6 * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  update-feeds:
    runs-on: ubuntu-latest

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Generate RSS feeds
        run: python generate.py

      - name: Commit updated feeds
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: Update journal RSS feeds
          file_pattern: docs/*.xml docs/index.html
```

解释：

```yaml
cron: "15 6 * * *"
```

表示每天 UTC 时间 06:15 运行一次。英国夏令时期间大约是英国时间 07:15，冬令时大约是 06:15。

```yaml
workflow_dispatch:
```

表示你也可以在 GitHub 页面手动点按钮运行。

---

# 十、启用 GitHub Pages

进入你的仓库页面：

```text
Settings → Pages
```

然后设置：

```text
Source: Deploy from a branch
Branch: main
Folder: /docs
```

保存。

GitHub Pages 会从 `main` 分支的 `/docs` 文件夹发布网站。([GitHub Docs][3])

几分钟后，你会得到 Pages 地址：

```text
https://你的GitHub用户名.github.io/journal-rss/
```

打开后应该能看到：

```text
Journal RSS Feeds
- Nature
- Science
- The Lancet
```

对应 RSS 地址就是：

```text
https://你的GitHub用户名.github.io/journal-rss/nature.xml
https://你的GitHub用户名.github.io/journal-rss/science.xml
https://你的GitHub用户名.github.io/journal-rss/lancet.xml
```

---

# 十一、手动运行一次

进入 GitHub 仓库：

```text
Actions → Update journal RSS feeds → Run workflow
```

运行完成后，回到仓库首页，看 `docs/` 目录下是否出现：

```text
nature.xml
science.xml
lancet.xml
index.html
```

如果有，说明自动生成成功。

---

# 十二、订阅 RSS

打开你的 RSS 阅读器，添加订阅源：

```text
https://你的GitHub用户名.github.io/journal-rss/nature.xml
```

然后重复添加其他期刊。

---

# 十三、添加新期刊

只需要编辑：

```text
journals.yml
```

例如添加：

```yaml
- name: Cell
  issn: 0092-8674
  slug: cell
  homepage: https://www.cell.com/cell/home
```

提交后，GitHub Actions 下次运行时会生成：

```text
docs/cell.xml
```

订阅地址就是：

```text
https://你的GitHub用户名.github.io/journal-rss/cell.xml
```

---

# 十四、排错

## 1. RSS 文件没生成

去看：

```text
Actions → Update journal RSS feeds → 最近一次运行 → Generate RSS feeds
```

常见原因：

```text
ISSN 写错
```

或者：

```text
Crossref 没有该期刊的记录
```

换另一个 ISSN 试试，尤其是 Online ISSN 和 Print ISSN。

---

## 2. RSS 阅读器说格式错误

检查 XML 文件里是否正常显示：

```xml
<rss version="2.0">
  <channel>
```

如果 RSS 阅读器很严格，可以把 `description` 里的摘要去掉，降低 XML 出错概率。修改 `build_rss()` 里这段：

```python
if abstract:
    description_parts.append(abstract)
```

改成注释：

```python
# if abstract:
#     description_parts.append(abstract)
```

---

## 3. 没有最新论文

Crossref 依赖出版社提交元数据。有些期刊官网已经更新，但 Crossref 会晚一点。

这种情况有三种处理方式：

```text
继续用 Crossref，接受延迟
```

```text
找期刊官方 RSS
```

```text
用 RSSHub 或自己抓期刊官网页面
```

---

## 4. Actions 没有自动运行

检查 `.github/workflows/update.yml` 是否在正确路径：

```text
.github/workflows/update.yml
```

再检查仓库的 Actions 是否被禁用。

也可以先手动运行：

```text
Actions → Run workflow
```

---

# 十五、推荐的最终维护方式

日常只维护一个文件：

```text
journals.yml
```

新增期刊就加一段：

```yaml
- name: 期刊名
  issn: ISSN
  slug: 文件名
  homepage: 期刊主页
```

每个期刊会自动生成一个 RSS：

```text
https://你的GitHub用户名.github.io/journal-rss/文件名.xml
```

这是最稳的基础版。后续如果你想做关键词过滤，可以在 `journals.yml` 里加字段，例如：

```yaml
keywords:
  - transformer
  - protein design
  - reinforcement learning
```

然后在 `generate.py` 里只保留标题或摘要命中关键词的文章。

[1]: https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-filters/?utm_source=chatgpt.com "REST API filters - Crossref"
[2]: https://docs.github.com/actions/using-workflows/events-that-trigger-workflows?utm_source=chatgpt.com "Events that trigger workflows"
[3]: https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site?utm_source=chatgpt.com "Configuring a publishing source for your GitHub Pages site"
[4]: https://www.rssboard.org/rss-draft-1?utm_source=chatgpt.com "RSS 2.0 Specification"
