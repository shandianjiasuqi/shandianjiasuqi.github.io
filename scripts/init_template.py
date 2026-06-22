from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SITE_FILE = ROOT / "content" / "site.yml"
TEMPLATE_DIR = ROOT / "templates"
HOME_TEMPLATE = TEMPLATE_DIR / "home.html"
ARTICLE_TEMPLATE = TEMPLATE_DIR / "article.html"
LOCK_FILE = TEMPLATE_DIR / "template.lock.json"
BRIEF_FILE = TEMPLATE_DIR / "design-brief.json"
STYLE_FILE = ROOT / "assets" / "css" / "style.css"
PROMPT_VERSION = 5

HOME_PLACEHOLDERS = {
    "$brand",
    "$tagline",
    "$description",
    "$answer_summary",
    "$last_updated",
    "$notice",
    "$article_count",
    "$article_cards",
    "$friend_cards",
    "$trust_points",
    "$topic_cards",
    "$home_faq_html",
    "$hero_image",
    "$articles_url",
}
HOME_REQUIRED_PLACEHOLDERS = {
    "$brand",
    "$article_cards",
    "$home_faq_html",
}
ARTICLE_PLACEHOLDERS = {
    "$article_title",
    "$article_description",
    "$category",
    "$date",
    "$author",
    "$notice",
    "$article_body",
    "$article_image",
    "$article_image_alt",
    "$article_image_caption",
    "$related_links",
    "$tag_html",
    "$faq_html",
    "$home_url",
    "$articles_url",
}
ARTICLE_REQUIRED_PLACEHOLDERS = {
    "$article_title",
    "$article_body",
    "$faq_html",
    "$related_links",
}
CSS_REQUIRED_MARKERS = {
    "body",
    ".container",
    ".site-header",
    ".nav-wrap",
    ".brand",
    ".site-footer",
    ".footer-grid",
    ".post-card",
    ".post-meta",
    ".text-link",
    ".faq-item",
    ".side-link",
    ".page-header",
    ".post-list",
}

COMPONENT_CONTRACT = """
外层 Python 只提供真实内容接口，不提供版式方案。theme_css 必须把这些
程序生成的结构纳入同一套完整视觉系统：
- body
- header.site-header > .container.nav-wrap > a.brand + nav > a
- footer.site-footer > .container.footer-grid
- 首页文章流：article.post-card > .post-meta + h2 > a + p + a.text-link
- 首页 FAQ：details.faq-item > summary + p
- 主题入口：a.topic-card > h3 + p
- 友情链接：a.friend-card > strong + span + small
- 文章相关文章：a.side-link > span + small
- 文章列表页：.page-header、.breadcrumb、.section、.post-list、.post-card
- Markdown 正文可能包含 h2、h3、p、ul、ol、blockquote、table、a、strong、code、pre、img

占位符会被替换成真实 HTML，包括文章路径链接。请直接围绕这些接口做设计，
不要把页面做成占位符外面套几个普通卡片。
"""


def read_config() -> dict:
    with SITE_FILE.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def write_config(config: dict) -> None:
    with SITE_FILE.open("w", encoding="utf-8") as file:
        yaml.safe_dump(config, file, allow_unicode=True, sort_keys=False)


def clean_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return json.loads(text)


def validate_template(name: str, text: str, required: set[str]) -> None:
    lowered = text.lower()
    forbidden = (
        "<html",
        "<head",
        "<body",
        "<main",
        "<script",
        "<style",
        "<link",
        "<iframe",
    )
    if any(fragment in lowered for fragment in forbidden):
        raise ValueError(f"{name} contains a forbidden executable or external element.")
    missing = sorted(required - {token for token in required if token in text})
    if missing:
        raise ValueError(f"{name} is missing placeholders: {', '.join(missing)}")
    if "<h1" not in lowered:
        raise ValueError(f"{name} must contain a semantic H1 heading.")
    if "<button" in lowered:
        raise ValueError(
            f"{name} contains a button, but this static theme has no button actions."
        )
    unsupported_claims = ("核验通过 日期戳", "点击弹出", "轮播")
    if any(claim in text for claim in unsupported_claims):
        raise ValueError(
            f"{name} describes an interaction or verification state not provided by the program."
        )


def sanitize_template_fragment(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"(?is)<!doctype[^>]*>", "", text)
    text = re.sub(r"(?is)<script\b[^>]*>.*?</script>", "", text)
    text = re.sub(r"(?is)<style\b[^>]*>.*?</style>", "", text)
    text = re.sub(r"(?is)<iframe\b[^>]*>.*?</iframe>", "", text)
    text = re.sub(r"(?is)<link\b[^>]*>", "", text)

    main_match = re.search(r"(?is)<main\b[^>]*>(.*?)</main>", text)
    if main_match:
        text = main_match.group(1).strip()
    else:
        body_match = re.search(r"(?is)<body\b[^>]*>(.*?)</body>", text)
        if body_match:
            text = body_match.group(1).strip()

    text = re.sub(r"(?is)</?(?:html|head|body|main)\b[^>]*>", "", text)
    return text.strip()


def validate_css(css: str) -> None:
    lowered = css.lower()
    if not css or "{" not in css or "}" not in css:
        raise ValueError("theme_css is empty or invalid.")
    if "@media" not in lowered:
        raise ValueError("theme_css must include responsive media rules.")
    missing = sorted(marker for marker in CSS_REQUIRED_MARKERS if marker not in lowered)
    if missing:
        raise ValueError(
            "theme_css does not style program-generated components: "
            + ", ".join(missing)
        )


def lock_version() -> int:
    if not LOCK_FILE.exists():
        return 0
    try:
        lock = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    return int(lock.get("prompt_version", 0))


def request_design(
    key: str,
    model: str,
    prompt: str,
    *,
    system: str,
    temperature: float,
    max_tokens: int,
) -> dict:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system,
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API error {error.code}: {detail}") from error
    choice = result["choices"][0]
    if choice.get("finish_reason") == "length":
        raise RuntimeError("DeepSeek output was truncated. Increase max_tokens.")
    content = choice.get("message", {}).get("content") or ""
    if not content.strip():
        raise RuntimeError("DeepSeek returned an empty JSON response.")
    return clean_json(content)


def design_brief_prompt(config: dict) -> str:
    return f"""
???????????{config['title']}???????????????????????? HTML ? CSS?

?????{config['description']}
??????????????????????????????????????????????????
??????????{config.get('hero_image', '')}

??????????????????????????????????????
- ??????????????????????????????????????????????
- ????? SEO ? GEO?????????????????????? AI ?????
- ?????????????????????????????????????????????????????????
- ??????????????????? AI ?????????????????????????
- ??????????????????????????????????????
- ??????????????????100%???????????????????
- ???????????SEO??GEO??AI ?????????????????

????? JSON?
{{
  "design_brief": {{
    "concept_name": "????",
    "theme_color": "#?????????",
    "brand_story": "????",
    "visual_direction": "??????",
    "palette": ["?????"],
    "typography": "?????????",
    "homepage_composition": "??????????????????",
    "article_experience": "????????????",
    "component_language": "?????????FAQ???????????",
    "responsive_strategy": "?????",
    "performance_strategy": "???????????",
    "geo_strategy": "?? AI ????????????",
    "signature_details": ["??????????"],
    "avoid": ["?????????"]
  }}
}}
"""


def implementation_prompt(config: dict, design_brief: dict) -> str:
    return f"""
You are generating partial HTML templates for a static site builder.
Hard constraints:
- Return JSON only.
- home_template and article_template must be HTML fragments for the inside of <main> only.
- Do not include <!doctype>, <html>, <head>, <body>, <main>, <script>, <style>, <link>, <iframe>, or <button>.
- Do not include external CSS, external JavaScript, inline JavaScript, analytics, ads, or tracking code.
- Use only normal links and details/summary for interaction.
- Keep all required placeholders exactly as provided.
- theme_css must contain all CSS.

?????????????????????????????????

???{config['title']}
???{config['description']}
?????
{json.dumps(design_brief, ensure_ascii=False, indent=2)}

?????
- Python ????????????????????????????????????????????????????????
- ????????????????????????????????????/????????????????FAQ?????????????
- ??????????????????????????????????????????????FAQ???????
- ??????? <main> ????????? main?html?head?body?style?link?script ? iframe?
- SEO head?canonical?Open Graph?JSON-LD????????? Python ?????
- ???????????????????? CSS/JS???? JavaScript ????????????

??????????????????????????????????
{", ".join(sorted(HOME_REQUIRED_PLACEHOLDERS))}

???????????????????
{", ".join(sorted(HOME_PLACEHOLDERS - HOME_REQUIRED_PLACEHOLDERS))}

???????????????
{", ".join(sorted(ARTICLE_REQUIRED_PLACEHOLDERS))}

????????????????????
{", ".join(sorted(ARTICLE_PLACEHOLDERS - ARTICLE_REQUIRED_PLACEHOLDERS))}

?????????
{COMPONENT_CONTRACT}

?????
- CSS ??????????????????????????????Markdown ??????FAQ????????? @media?
- ????????????? h1?????? section?article?nav?aside?
- ???????????? details/summary????? button????????? JavaScript ????????
- ???????????????????????????????????????????
- ???????? AI ????SEO??GEO????????????????
- ????????????????????????????????????????

????? JSON?
{{
  "home_template": "<main ??????? HTML>",
  "article_template": "<main ???????? HTML>",
  "theme_css": "???????????? CSS"
}}
"""


def review_prompt(design_brief: dict, home: str, article: str, css: str) -> str:
    return f"""
请担任严格的网页设计总监，复审下面这套网站主题。

原始创意方案：
{json.dumps(design_brief, ensure_ascii=False, indent=2)}

当前首页模板：
{home}

当前文章页模板：
{article}

当前 CSS：
{css}

程序组件结构：
{COMPONENT_CONTRACT}

请主动修正任何“像骨架、像默认模板、官网感不足、区块不完整、视觉单薄、层级不清、留白粗糙、组件未设计、文章阅读体验不足、移动端处理敷衍”的问题。
保留必要占位符，不要缩减完成度。你可以重构 HTML 和 CSS，只要继续忠于创意方案并保持纯静态实现。
不要输出无功能按钮、轮播、弹窗，也不要显示程序没有提供的核验状态。

只返回严格 JSON：
{{
  "home_template": "复审后的完整首页 HTML",
  "article_template": "复审后的完整文章页 HTML",
  "theme_css": "复审后的完整 CSS"
}}
"""


def generate() -> None:
    current_version = lock_version()
    if current_version >= PROMPT_VERSION:
        raise RuntimeError(
            f"Template v{current_version} is already locked. Regeneration is disabled."
        )
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is required.")

    config = read_config()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
    brief_result = request_design(
        key,
        model,
        design_brief_prompt(config),
        system="你是有独立审美判断的品牌创意总监，只输出可解析 JSON。",
        temperature=1.0,
        max_tokens=5000,
    )
    design_brief = brief_result.get("design_brief", brief_result)
    if not isinstance(design_brief, dict) or not design_brief:
        raise ValueError("DeepSeek did not return a usable design brief.")

    base_prompt = implementation_prompt(config, design_brief)
    validation_error = ""
    for attempt in range(1, 4):
        attempt_prompt = base_prompt
        if validation_error:
            attempt_prompt += (
                "\n\nThe previous implementation failed validation: "
                f"{validation_error}\n"
                "Fix the issue and return complete JSON again. "
                "Templates are fragments inside <main> only; no html/head/body/main/script/style/link/iframe/button."
            )
        generated = request_design(
            key,
            model,
            attempt_prompt,
            system="你是兼具审美和工程能力的资深前端设计师，只输出可解析 JSON。",
            temperature=0.8,
            max_tokens=12000,
        )
        home = sanitize_template_fragment(generated.get("home_template", ""))
        article = sanitize_template_fragment(generated.get("article_template", ""))
        css = str(generated.get("theme_css", "")).strip()
        try:
            validate_template("home_template", home, HOME_REQUIRED_PLACEHOLDERS)
            validate_template("article_template", article, ARTICLE_REQUIRED_PLACEHOLDERS)
            validate_css(css)
        except ValueError as error:
            validation_error = str(error)
            if attempt == 3:
                raise
            continue
        break

    try:
        reviewed = request_design(
            key,
            model,
            review_prompt(design_brief, home, article, css),
            system="你是要求很高的数字产品设计总监，只输出复审完成后的可解析 JSON。",
            temperature=0.65,
            max_tokens=14000,
        )
        reviewed_home = sanitize_template_fragment(reviewed.get("home_template", ""))
        reviewed_article = sanitize_template_fragment(reviewed.get("article_template", ""))
        reviewed_css = str(reviewed.get("theme_css", "")).strip()
        validate_template("home_template", reviewed_home, HOME_REQUIRED_PLACEHOLDERS)
        validate_template("article_template", reviewed_article, ARTICLE_REQUIRED_PLACEHOLDERS)
        validate_css(reviewed_css)
        home, article, css = reviewed_home, reviewed_article, reviewed_css
    except (KeyError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"Design review was skipped; using the validated implementation: {error}")

    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    theme_color = str(design_brief.get("theme_color", "")).strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", theme_color):
        config["theme_color"] = theme_color
        write_config(config)
    BRIEF_FILE.write_text(
        json.dumps(design_brief, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    HOME_TEMPLATE.write_text(home + "\n", encoding="utf-8")
    ARTICLE_TEMPLATE.write_text(article + "\n", encoding="utf-8")
    STYLE_FILE.write_text(css + "\n", encoding="utf-8")
    LOCK_FILE.write_text(
        json.dumps(
            {
                "brand": config["title"],
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "concept_name": design_brief.get("concept_name", ""),
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "regeneration": "disabled",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("One-time DeepSeek templates generated and locked.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the site template once.")
    parser.parse_args()
    generate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
