from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from string import Template

import markdown
import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = ROOT / "content"
ARTICLE_DIR = CONTENT_DIR / "articles"
LOCAL_DIR = ROOT / "local"
SITE_FILE = CONTENT_DIR / "site.yml"
DEFAULT_KEYWORDS = LOCAL_DIR / "keywords.txt"
LOCAL_DEEPSEEK_KEY = LOCAL_DIR / "deepseek.key"
LOCAL_INDEXNOW_KEY = LOCAL_DIR / "indexnow.key"
TEMPLATE_DIR = ROOT / "templates"
HOME_TEMPLATE = TEMPLATE_DIR / "home.html"
ARTICLE_TEMPLATE = TEMPLATE_DIR / "article.html"
TEMPLATE_LOCK = TEMPLATE_DIR / "template.lock.json"


def read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def write_yaml(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def site_url(config: dict, override: str | None = None) -> str:
    value = override or os.getenv("SITE_URL") or config.get("site_url") or "https://shandianjiasuqi.github.io"
    return str(value).strip().rstrip("/")


def base_path_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path.rstrip("/")
    return "" if path in ("", "/") else path


def site_path(config: dict, path: str) -> str:
    value = str(path or "")
    if not value or value.startswith(("#", "http://", "https://", "mailto:", "tel:")):
        return value
    if not value.startswith("/"):
        value = f"/{value}"
    prefix = config.get("_base_path", "")
    if value == "/":
        return f"{prefix}/" if prefix else "/"
    return f"{prefix}{value}"


def deepseek_key() -> str | None:
    if os.getenv("DEEPSEEK_API_KEY"):
        return os.getenv("DEEPSEEK_API_KEY", "").strip()
    if LOCAL_DEEPSEEK_KEY.exists():
        return LOCAL_DEEPSEEK_KEY.read_text(encoding="utf-8").strip()
    return None


def indexnow_key() -> str | None:
    if os.getenv("INDEXNOW_KEY"):
        return os.getenv("INDEXNOW_KEY", "").strip()
    if LOCAL_INDEXNOW_KEY.exists():
        return LOCAL_INDEXNOW_KEY.read_text(encoding="utf-8").strip()
    return None


def slugify(text: str) -> str:
    ascii_text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    if ascii_text:
        return ascii_text[:80]
    return "post-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def markdown_html(text: str) -> str:
    return markdown.markdown(text or "", extensions=["extra", "tables", "sane_lists"])


def article_url(article: dict) -> str:
    return f"/articles/{article['slug']}.html"


def article_path(article: dict) -> Path:
    return ROOT / "articles" / f"{article['slug']}.html"


def template_body(path: Path, values: dict[str, object]) -> str:
    if not TEMPLATE_LOCK.exists() or not path.exists():
        raise RuntimeError(
            "Site templates are not initialized. Run the "
            "'Initialize DeepSeek Template' workflow once."
        )
    rendered = Template(path.read_text(encoding="utf-8")).safe_substitute(
        {key: str(value or "") for key, value in values.items()}
    )
    unresolved = sorted(set(re.findall(r"\$[A-Za-z_][A-Za-z0-9_]*", rendered)))
    if unresolved:
        raise ValueError(f"Unresolved template placeholders: {', '.join(unresolved)}")
    return rendered


def load_articles() -> list[dict]:
    articles = []
    for path in ARTICLE_DIR.glob("*.json"):
        item = read_json(path)
        item["_source"] = path.name
        articles.append(item)
    articles.sort(key=lambda item: (item.get("date", ""), item.get("title", "")), reverse=True)
    return articles


def layout(
    config: dict,
    title: str,
    description: str,
    body: str,
    canonical: str,
    keywords: str = "",
    structured_data: list[dict] | None = None,
    page_type: str = "website",
    published_date: str = "",
    modified_date: str = "",
) -> str:
    brand_name = config.get("brand") or config["title"]
    nav = "".join(
        f'<a href="{esc(site_path(config, item["url"]))}">{esc(item["name"])}</a>'
        for item in config.get("nav", [])
    )
    full_title = title if title == config["title"] else f"{title} | {config['title']}"
    asset_version = urllib.parse.quote(str(config.get("_asset_version", "")))
    social_image = config.get("_base_url", site_url(config)) + config.get("default_image", "")
    schemas = "".join(
        f'<script type="application/ld+json">{json.dumps(item, ensure_ascii=False)}</script>'
        for item in (structured_data or [])
    )
    article_meta = ""
    if published_date:
        article_meta += (
            f'<meta property="article:published_time" content="{esc(published_date)}">'
        )
    if modified_date:
        article_meta += (
            f'<meta property="article:modified_time" content="{esc(modified_date)}">'
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(full_title)}</title>
  <meta name="description" content="{esc(description)}">
  <meta name="keywords" content="{esc(keywords or config.get("keywords", ""))}">
  <meta name="author" content="{esc(config.get("author"))}">
  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
  <meta name="googlebot" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
  <meta name="bingbot" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1">
  <meta name="referrer" content="strict-origin-when-cross-origin">
  <meta name="theme-color" content="{esc(config.get("theme_color", "#087f73"))}">
  <link rel="canonical" href="{esc(canonical)}">
  <link rel="alternate" hreflang="zh-CN" href="{esc(canonical)}">
  <link rel="alternate" hreflang="x-default" href="{esc(canonical)}">
  <meta property="og:locale" content="zh_CN">
  <meta property="og:type" content="{esc(page_type)}">
  <meta property="og:site_name" content="{esc(config['title'])}">
  <meta property="og:title" content="{esc(full_title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{esc(canonical)}">
  <meta property="og:image" content="{esc(social_image)}">
  <meta property="og:image:alt" content="{esc(config['title'])}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(full_title)}">
  <meta name="twitter:description" content="{esc(description)}">
  <meta name="twitter:image" content="{esc(social_image)}">
  {article_meta}
  <link rel="stylesheet" href="{esc(site_path(config, "/assets/css/style.css"))}?v={asset_version}">
  <link rel="stylesheet" href="{esc(site_path(config, "/assets/css/responsive-fixes.css"))}?v={asset_version}">
  <link rel="alternate" type="application/rss+xml" title="{esc(config['title'])}" href="{esc(site_path(config, "/feed.xml"))}">
  {schemas}
</head>
<body>
  <header class="site-header">
    <div class="container nav-wrap">
      <a class="brand" href="{esc(site_path(config, "/"))}"><span></span>{esc(brand_name)}</a>
      <nav>{nav}</nav>
    </div>
  </header>
  <main>{body}</main>
  <footer class="site-footer">
    <div class="container footer-grid">
      <div><strong>{esc(brand_name)}</strong><p>{esc(config['description'])}</p></div>
      <div><a href="{esc(site_path(config, "/articles/"))}">文章列表</a><a href="{esc(site_path(config, "/sitemap.xml"))}">站点地图</a><a href="{esc(site_path(config, "/feed.xml"))}">RSS</a></div>
    </div>
  </footer>
  <script src="{esc(site_path(config, "/assets/js/main.js"))}?v={asset_version}"></script>
</body>
</html>
"""


def render_home(config: dict, articles: list[dict], base_url: str) -> None:
    brand_name = config.get("brand") or config["title"]
    latest = articles[:10]
    article_cards = "".join(
        f"""<article class="post-card">
          <div class="post-meta"><time datetime="{esc(item.get("date"))}">{esc(item.get("date"))}</time><span>{esc(item.get("category"))}</span></div>
          <h2><a href="{esc(site_path(config, article_url(item)))}">{esc(item.get("title"))}</a></h2>
          <p>{esc(item.get("description"))}</p>
          <a class="text-link" href="{esc(site_path(config, article_url(item)))}">查看详细说明</a>
        </article>"""
        for item in latest
    )
    friends = "".join(
        f"""<a class="friend-card" href="{esc(item.get("url"))}" rel="nofollow noopener" target="_blank">
          <strong>{esc(item.get("name"))}</strong>
          <span>{esc(item.get("desc"))}</span>
          <small>核验：{esc(item.get("last_checked"))}</small>
        </a>"""
        for item in config.get("friends", [])
    )
    if not friends:
        friends = '<p class="empty-state">友情链接位置已预留，确认合作站点后再公开展示。</p>'
    trust_points = "".join(
        f"<li>{esc(item)}</li>" for item in config.get("trust_points", [])
    )
    topic_cards = "".join(
        f"""<a class="topic-card" href="{esc(site_path(config, "/articles/"))}">
          <h3>{esc(item.get("name"))}</h3>
          <p>{esc(item.get("desc"))}</p>
        </a>"""
        for item in config.get("topics", [])
    )
    home_faq = [
        item
        for item in config.get("home_faq", [])
        if isinstance(item, dict) and item.get("question") and item.get("answer")
    ]
    home_faq_html = "".join(
        f"""<details class="faq-item">
          <summary>{esc(item["question"])}</summary>
          <p>{esc(item["answer"])}</p>
        </details>"""
        for item in home_faq
    )
    body = template_body(
        HOME_TEMPLATE,
        {
            "brand": esc(brand_name),
            "tagline": esc(config.get("tagline")),
            "description": esc(config["description"]),
            "answer_summary": esc(config.get("answer_summary")),
            "last_updated": esc(config.get("last_updated")),
            "notice": esc(config.get("notice")),
            "article_count": len(articles),
            "article_cards": article_cards,
            "friend_cards": friends,
            "trust_points": trust_points,
            "topic_cards": topic_cards,
            "home_faq_html": home_faq_html,
            "hero_image": esc(site_path(config, config.get("hero_image"))),
            "articles_url": esc(site_path(config, "/articles/")),
        },
    )
    schemas = [
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "@id": f"{base_url}/#website",
            "name": config["title"],
            "url": f"{base_url}/",
            "description": config["description"],
            "inLanguage": "zh-CN",
        },
        {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "@id": f"{base_url}/#webpage",
            "url": f"{base_url}/",
            "name": config["title"],
            "description": config["description"],
            "dateModified": config.get("last_updated"),
            "isPartOf": {"@id": f"{base_url}/#website"},
            "about": {
                "@type": "Thing",
                "name": "闪电加速器官网入口、备用地址和使用教程",
            },
            "inLanguage": "zh-CN",
        },
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "@id": f"{base_url}/#organization",
            "name": config["title"],
            "url": f"{base_url}/",
            "logo": base_url + config.get("default_image", ""),
        },
    ]
    if home_faq:
        schemas.append(
            {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["question"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": item["answer"],
                        },
                    }
                    for item in home_faq
                ],
            }
        )
    (ROOT / "index.html").write_text(
        layout(
            config,
            config["title"],
            config["description"],
            body,
            f"{base_url}/",
            config.get("keywords", ""),
            schemas,
            "website",
            config.get("last_updated", ""),
            config.get("last_updated", ""),
        ),
        encoding="utf-8",
    )


def render_article(config: dict, article: dict, articles: list[dict], base_url: str) -> None:
    related = "".join(
        f'<a class="side-link" href="{esc(site_path(config, article_url(item)))}"><span>{esc(item["title"][:28])}</span><small>{esc(item.get("date"))}</small></a>'
        for item in [
            candidate
            for candidate in articles
            if candidate.get("slug") != article.get("slug")
        ][:6]
    )
    tag_html = "".join(f"<span>{esc(tag)}</span>" for tag in article.get("tags", []))
    body_html = markdown_html(article.get("body_markdown", ""))
    image = article.get("image") or config.get("default_image", "/assets/img/hero.png")
    faq_items = [
        item
        for item in article.get("faq", [])
        if isinstance(item, dict) and item.get("question") and item.get("answer")
    ]
    faq_html = "".join(
        f"<details><summary>{esc(item['question'])}</summary><p>{esc(item['answer'])}</p></details>"
        for item in faq_items
    )
    body = template_body(
        ARTICLE_TEMPLATE,
        {
            "article_title": esc(article["title"]),
            "article_description": esc(article.get("description")),
            "category": esc(article.get("category")),
            "date": esc(article.get("date")),
            "author": esc(config.get("author")),
            "notice": esc(config.get("notice")),
            "article_body": body_html,
            "article_image": esc(site_path(config, image)),
            "article_image_alt": esc(article.get("image_alt", article["title"])),
            "article_image_caption": esc(article.get("image_caption", "")),
            "related_links": related,
            "tag_html": tag_html,
            "faq_html": faq_html,
            "home_url": esc(site_path(config, "/")),
            "articles_url": esc(site_path(config, "/articles/")),
        },
    )
    article_schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article["title"],
        "description": article.get("description", ""),
        "datePublished": article.get("date"),
        "dateModified": article.get("date"),
        "author": {"@type": "Organization", "name": config.get("author")},
        "publisher": {"@type": "Organization", "name": config["title"]},
        "mainEntityOfPage": f"{base_url}{article_url(article)}",
        "image": base_url + image,
        "inLanguage": "zh-CN",
    }
    schemas = [article_schema]
    schemas.append(
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": "首页",
                    "item": f"{base_url}/",
                },
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": "使用文章",
                    "item": f"{base_url}/articles/",
                },
                {
                    "@type": "ListItem",
                    "position": 3,
                    "name": article["title"],
                    "item": f"{base_url}{article_url(article)}",
                },
            ],
        }
    )
    if faq_items:
        schemas.append(
            {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["question"],
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": item["answer"],
                        },
                    }
                    for item in faq_items
                ],
            }
        )
    path = article_path(article)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        layout(
            config,
            article["title"],
            article.get("description", article["title"]),
            body,
            f"{base_url}{article_url(article)}",
            article.get("keywords", ""),
            schemas,
            "article",
            article.get("date", ""),
            article.get("date", ""),
        ),
        encoding="utf-8",
    )


def render_articles_index(config: dict, articles: list[dict], base_url: str) -> None:
    cards = "".join(
        f"""<article class="post-card">
          <div class="post-meta">{esc(item.get("date"))} ? {esc(item.get("category"))}</div>
          <h2><a href="{esc(site_path(config, article_url(item)))}">{esc(item.get("title"))}</a></h2>
          <p>{esc(item.get("description"))}</p>
        </article>"""
        for item in articles
    )
    brand_name = config.get("brand") or config["title"]
    body = f"""<section class="page-header"><div class="container"><a class="breadcrumb" href="{esc(site_path(config, "/"))}">首页</a><h1>闪电加速器使用文章</h1><p>{esc(brand_name)}整理的官网下载、备用入口、打不开排查与使用教程。</p></div></section>
<section class="section"><div class="container"><div class="post-list">{cards}</div></div></section>"""
    path = ROOT / "articles" / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(layout(config, "使用文章", config["description"], body, f"{base_url}/articles/"), encoding="utf-8")

def update_site_dates(config: dict) -> dict:
    today = dt.date.today().strftime("%Y-%m-%d")
    config["last_updated"] = today
    for friend in config.get("friends", []):
        friend["last_checked"] = today
    write_yaml(SITE_FILE, config)
    return config


def build(args: argparse.Namespace) -> None:
    config = update_site_dates(read_yaml(SITE_FILE))
    base_url = site_url(config, args.site_url)
    config["_base_path"] = base_path_from_url(base_url)
    config["_base_url"] = base_url
    config["_asset_version"] = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    articles = load_articles()
    clean_orphan_article_pages(articles)
    for article in articles:
        render_article(config, article, articles, base_url)
    render_articles_index(config, articles, base_url)
    render_home(config, articles, base_url)
    render_sitemap(config, articles, base_url)
    render_feed(config, articles, base_url)
    render_robots(config, base_url)
    write_indexnow_key()
    print(f"Built {len(articles)} articles.")


def clean_orphan_article_pages(articles: list[dict]) -> None:
    output_dir = ROOT / "articles"
    if not output_dir.exists():
        return
    keep = {"index.html"} | {f"{item['slug']}.html" for item in articles if item.get("slug")}
    for path in output_dir.glob("*.html"):
        if path.name not in keep:
            path.unlink()


def render_sitemap(config: dict, articles: list[dict], base_url: str) -> None:
    today = dt.date.today().strftime("%Y-%m-%d")
    urls = [("/", today), ("/articles/", today)]
    urls.extend((article_url(item), item.get("date", today)) for item in articles)
    body = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, lastmod in urls:
        body.append(f"<url><loc>{esc(base_url + loc)}</loc><lastmod>{esc(lastmod)}</lastmod></url>")
    body.append("</urlset>")
    (ROOT / "sitemap.xml").write_text("\n".join(body), encoding="utf-8")


def render_feed(config: dict, articles: list[dict], base_url: str) -> None:
    items = []
    for article in articles[:20]:
        pub = email.utils.format_datetime(dt.datetime.fromisoformat(article.get("date") + "T08:00:00+08:00"))
        items.append(
            f"""<item><title>{esc(article['title'])}</title><link>{esc(base_url + article_url(article))}</link><guid>{esc(base_url + article_url(article))}</guid><pubDate>{esc(pub)}</pubDate><description>{esc(article.get('description', ''))}</description></item>"""
        )
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>{esc(config['title'])}</title><link>{esc(base_url)}/</link><description>{esc(config['description'])}</description>{''.join(items)}</channel></rss>"""
    (ROOT / "feed.xml").write_text(feed, encoding="utf-8")


def render_robots(config: dict, base_url: str) -> None:
    (ROOT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {base_url}/sitemap.xml\n", encoding="utf-8")


def clean_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


def fallback_article(keyword: str, config: dict) -> dict:
    today = dt.date.today().strftime("%Y-%m-%d")
    brand = config.get("brand") or "闪电加速器"
    return {
        "title": f"{keyword}：官网入口、备用地址与使用说明",
        "slug": slugify(keyword),
        "date": today,
        "category": "使用指南",
        "tags": ["官网下载", "备用入口", "打不开排查", "使用教程"],
        "keywords": f"{keyword},{brand}官网,{brand}下载,{brand}备用入口,{brand}打不开怎么办,{brand}使用教程",
        "description": f"整理{keyword}相关的官网入口、备用访问地址、客户端下载说明、打不开排查方法和使用提醒。",
        "image": config.get("default_image", "/assets/img/shandianjiasuqi-hero.svg"),
        "image_alt": f"{keyword}官网发布信息整理",
        "image_caption": f"{keyword}官网入口与使用说明，更新日期：{today}",
        "body_markdown": f"""## 直接结论

本文围绕 **{keyword}** 整理官网入口、备用访问地址、客户端下载和使用排查信息。入口和版本可能变化，请优先以本站最新发布页和页面更新时间为准，不要在来源不明的页面输入账号、支付或设备信息。

## 信息概览

| 项目 | 内容 |
| --- | --- |
| 关键词 | {keyword} |
| 信息类型 | 官网入口 / 备用地址 / 下载说明 / 使用教程 |
| 更新日期 | {today} |

## 如何核对官网入口

1. 优先从本站首页进入最新发布信息。
2. 检查页面域名、证书、页面标题和更新时间是否一致。
3. 下载客户端前确认文件名称、来源页面和系统版本。
4. 遇到跳转异常、弹窗诱导或陌生网盘链接时先停止操作。

## 打不开时可以先检查

- 当前网络是否稳定，浏览器是否开启了异常代理或扩展。
- DNS、缓存、系统时间和安全软件是否影响访问。
- 是否存在临时维护、入口调整或地区网络波动。
- 是否访问了仿冒页面或过期入口。

## 风险提醒

本站不会编造不可验证的下载地址、永久可用承诺、账号信息或付费结果。下载和登录前，请自行核对来源可信度。
""",
        "faq": [
            {"question": f"{keyword}入口一定可用吗？", "answer": "不一定。官网入口和备用地址可能因维护、访问环境或发布策略变化而调整，请以当前页面展示的信息和更新时间为准。"},
            {"question": f"{keyword}打不开怎么办？", "answer": "可以先检查网络、浏览器缓存、DNS、系统时间和安全软件拦截，再查看备用入口与排查说明。"},
            {"question": f"{keyword}下载时要注意什么？", "answer": "下载前应核对页面来源、域名、证书和文件名称，避免从陌生网盘、群聊或二次分发页面安装未知文件。"},
            {"question": "这里会发布账号或付费承诺吗？", "answer": "不会。本站只整理入口、下载、教程和排查信息，不编造账号、价格、永久有效或性能承诺。"},
        ],
    }


def article_prompt(keyword: str, today: str) -> str:
    return f"""
围绕关键词「{keyword}」生成一篇中文内容详情页文章，主题聚焦闪电加速器官网入口、官网下载、备用访问地址、打不开排查和使用教程。

写作目标：
- 内容要像官方网站内容中心的专业文章页，不要只有几段空泛说明。
- 开头用 2-3 句话直接回答用户搜索意图，适合搜索摘要和 AI 搜索引用。
- 正文 Markdown 至少包含：直接结论、信息概览表、官网入口核对方法、客户端下载注意事项、打不开原因、备用入口使用建议、操作步骤、检查清单、风险提醒、更新说明。
- FAQ 答案要能独立理解，并自然覆盖长尾搜索词。
- 不编造具体下载地址、备用域名、账号、价格、节点数量、永久有效、速度承诺、付费结果或 token。
- 如果没有明确官方链接，写“请以本站首页当前展示入口和页面更新时间为准”，不要补造链接。
- 固定图片为站内图，只生成 image_alt 和 image_caption。
- 日期使用 {today}。
- 页面文案不要出现“SEO”“GEO”“AI 生成”“模板”“占位符”等实现说明。

只输出严格 JSON，字段为：
title, category, tags, keywords, description, image_alt, image_caption, body_markdown, faq
"""

def generate_deepseek_article(keyword: str, config: dict) -> dict:
    key = deepseek_key()
    if not key:
        print("No DeepSeek key found, using fallback article.")
        return fallback_article(keyword, config)
    today = dt.date.today().strftime("%Y-%m-%d")
    prompt = article_prompt(keyword, today)
    payload = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": "Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.65,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API error {error.code}: {detail}") from error
    article = clean_json(result["choices"][0]["message"]["content"])
    article["date"] = today
    article["slug"] = slugify(keyword) + "-" + hashlib.sha1(article["title"].encode("utf-8")).hexdigest()[:8]
    article["image"] = config.get("default_image", "/assets/img/hero.png")
    return article


def save_article(article: dict) -> Path:
    ARTICLE_DIR.mkdir(parents=True, exist_ok=True)
    source = ARTICLE_DIR / f"{article['date']}-{article['slug']}.json"
    counter = 2
    while source.exists():
        source = ARTICLE_DIR / f"{article['date']}-{article['slug']}-{counter}.json"
        counter += 1
    write_json(source, article)
    print(f"Created {source}")
    return source


def new_article(args: argparse.Namespace) -> None:
    config = read_yaml(SITE_FILE)
    article = fallback_article(args.keyword, config) if args.no_ai else generate_deepseek_article(args.keyword, config)
    if "slug" not in article:
        article["slug"] = slugify(args.keyword) + "-" + hashlib.sha1(article["title"].encode("utf-8")).hexdigest()[:8]
    if "date" not in article:
        article["date"] = dt.date.today().strftime("%Y-%m-%d")
    if "image" not in article:
        article["image"] = config.get("default_image", "/assets/img/hero.png")
    save_article(article)
    build(argparse.Namespace(site_url=args.site_url))


def keyword_lines(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"keyword file not found: {path}")
    return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip() and not line.strip().startswith("#")]


def select_keywords(keywords: list[str], limit: int, rotate: bool = False) -> list[str]:
    if limit <= 0 or not keywords:
        return []
    count = min(limit, len(keywords))
    if not rotate:
        return keywords[:count]
    run_number = os.getenv("GITHUB_RUN_NUMBER", "")
    if run_number.isdigit():
        start = (int(run_number) - 1) % len(keywords)
    else:
        start = dt.date.today().toordinal() % len(keywords)
    return [keywords[(start + index) % len(keywords)] for index in range(count)]


def batch(args: argparse.Namespace) -> None:
    config = read_yaml(SITE_FILE)
    source = Path(args.file or DEFAULT_KEYWORDS)
    env_keywords = os.getenv("KEYWORDS")
    keywords = [line.strip() for line in env_keywords.splitlines() if line.strip()] if env_keywords else keyword_lines(source)
    selected = select_keywords(keywords, args.limit, rotate=bool(env_keywords))
    for keyword in selected:
        article = fallback_article(keyword, config) if args.no_ai else generate_deepseek_article(keyword, config)
        if "slug" not in article:
            article["slug"] = slugify(keyword) + "-" + hashlib.sha1(article["title"].encode("utf-8")).hexdigest()[:8]
        if "date" not in article:
            article["date"] = dt.date.today().strftime("%Y-%m-%d")
        if "image" not in article:
            article["image"] = config.get("default_image", "/assets/img/hero.png")
        save_article(article)
    build(argparse.Namespace(site_url=args.site_url))


def write_indexnow_key() -> None:
    key = indexnow_key()
    if key:
        (ROOT / f"{key}.txt").write_text(key, encoding="utf-8")


def indexnow(args: argparse.Namespace) -> None:
    config = read_yaml(SITE_FILE)
    base_url = site_url(config, args.site_url)
    key = indexnow_key()
    if not key:
        print("No INDEXNOW_KEY/local indexnow.key found, skip.")
        return
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}", key):
        print("INDEXNOW_KEY must be 8-128 letters, numbers, or dashes. Skip IndexNow.")
        return
    key_location = f"{base_url}/{key}.txt"
    key_ready = False
    for attempt in range(1, 13):
        check_url = f"{key_location}?check={int(time.time())}"
        check_request = urllib.request.Request(
            check_url,
            headers={"User-Agent": "shandianjiasuqi-indexnow/1.0", "Cache-Control": "no-cache"},
        )
        try:
            with urllib.request.urlopen(check_request, timeout=20) as response:
                content = response.read().decode("utf-8", errors="replace").strip()
                if response.status == 200 and content == key:
                    key_ready = True
                    print(f"IndexNow key file verified: {key_location}")
                    break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            pass
        print(f"Waiting for GitHub Pages to publish IndexNow key ({attempt}/12)...")
        time.sleep(10)
    if not key_ready:
        print(f"IndexNow key file is not available yet, skip this notification: {key_location}")
        return
    urls = [f"{base_url}/", f"{base_url}/articles/"]
    urls += [base_url + article_url(article) for article in load_articles()]
    failures: list[str] = []
    accepted = 0
    for url in sorted(set(urls)):
        query = urllib.parse.urlencode({"url": url, "key": key})
        request = urllib.request.Request(
            f"https://www.bing.com/indexnow?{query}",
            headers={"User-Agent": "shandianjiasuqi-indexnow/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status in {200, 202}:
                    accepted += 1
                else:
                    failures.append(f"{url} (HTTP {response.status})")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace").strip()
            failures.append(f"{url} (HTTP {error.code}: {detail or error.reason})")
        except (urllib.error.URLError, TimeoutError) as error:
            failures.append(f"{url} ({error})")

    print(f"IndexNow accepted {accepted}/{len(set(urls))} URLs.")
    if failures:
        print("::error title=IndexNow submission failed::Bing rejected one or more URLs.")
        raise RuntimeError("IndexNow rejected URLs:\n" + "\n".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description="Pure HTML builder for shandianjiasuqi.github.io")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build")
    p_build.add_argument("--site-url", default=None)
    p_build.set_defaults(func=build)

    p_new = sub.add_parser("new")
    p_new.add_argument("keyword")
    p_new.add_argument("--no-ai", action="store_true")
    p_new.add_argument("--site-url", default=None)
    p_new.set_defaults(func=new_article)

    p_batch = sub.add_parser("batch")
    p_batch.add_argument("--file", default=None)
    p_batch.add_argument("--limit", type=int, default=1)
    p_batch.add_argument("--no-ai", action="store_true")
    p_batch.add_argument("--site-url", default=None)
    p_batch.set_defaults(func=batch)

    p_indexnow = sub.add_parser("indexnow")
    p_indexnow.add_argument("--site-url", default=None)
    p_indexnow.set_defaults(func=indexnow)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
