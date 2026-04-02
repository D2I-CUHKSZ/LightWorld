#!/usr/bin/env python3
"""
Fetch a Baidu Baike event page and convert it into a LightWorld-ready event folder.

Outputs:
- source_page.html
- page_data.json
- event_overview.md
- event_timeline.txt
- video_entries.txt
- source_manifest.json
- images/*

This script is intentionally conservative:
- It downloads page HTML and images.
- It extracts embedded `window.PAGE_DATA`.
- It stores video metadata from the page.
- It does not promise downloadable video files because Baidu video endpoints
  often trigger anti-bot verification.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def fetch_url(url: str, user_agent: str = DEFAULT_USER_AGENT) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def extract_page_data(html: str) -> Dict[str, Any]:
    match = re.search(r"<script>window\.PAGE_DATA=\s*(\{.*?\})</script>", html, re.S)
    if not match:
        raise RuntimeError("未在页面中找到 window.PAGE_DATA")
    return json.loads(match.group(1))


def normalize_date(item: Dict[str, Any]) -> str:
    for key in ("publishDate", "refDate"):
        value = str(item.get(key, "") or "").strip()
        if value:
            return value
    return ""


def text_from_data_items(items: Iterable[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for item in items:
        text_items = item.get("text", []) if isinstance(item, dict) else []
        if isinstance(text_items, list):
            parts.append("".join(str(x.get("text", "") or "") for x in text_items if isinstance(x, dict)))
    return "".join(p for p in parts if p)


def extract_card_markdown(card: Dict[str, Any]) -> str:
    lines = ["## 基本信息", ""]
    for side_key in ("left", "right"):
        for item in card.get(side_key, []) or []:
            title = str(item.get("title", "") or "").strip()
            value = ""
            if isinstance(item.get("data"), list):
                fragments: List[str] = []
                for row in item.get("data", []):
                    if isinstance(row, dict):
                        fragments.append(text_from_data_items([row]))
                value = "；".join(x for x in fragments if x)
            if title and value:
                lines.append(f"- {title}：{value}")
    return "\n".join(lines).strip()


def extract_knowledge_sections(page_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    section_titles = OrderedDict((item.get("uuid"), item.get("title")) for item in page_data.get("catalog", []) or [])
    for module in page_data.get("modules", {}).get("knowledge", {}).get("data", []) or []:
        for block in module.get("data", []) or []:
            data = block.get("data", {}) if isinstance(block, dict) else {}
            body_uuid = block.get("uuid")
            title = ""
            if body_uuid and body_uuid.startswith("BoDY"):
                title = section_titles.get(body_uuid[4:], "")
            if not title:
                catalog = data.get("catalog", []) or []
                if catalog:
                    title = " / ".join(
                        str(item.get("title", "") or "").strip()
                        for item in catalog
                        if str(item.get("title", "") or "").strip()
                    )
            paragraphs = []
            for item in data.get("content", []) or []:
                if isinstance(item, dict):
                    text = str(item.get("text", "") or "").strip()
                    if text:
                        paragraphs.append(text)
            if paragraphs:
                sections.append(
                    {
                        "title": title or "补充内容",
                        "paragraphs": paragraphs,
                    }
                )
    return sections


def extract_reference_timeline(page_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = []
    for ref in page_data.get("reference", []) or []:
        title = str(ref.get("title", "") or "").strip()
        site = str(ref.get("site", "") or "").strip()
        date = normalize_date(ref)
        encode_url = str(ref.get("encodeUrl", "") or "").strip()
        items.append(
            {
                "date": date,
                "site": site,
                "title": title,
                "encodeUrl": encode_url,
                "uuid": ref.get("uuid"),
            }
        )
    items.sort(key=lambda row: (row["date"] or "9999-99-99", row["title"]))
    return items


def build_image_entries(page_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for album in page_data.get("albums", []) or []:
        album_desc = str(album.get("desc", "") or "").strip()
        for idx, item in enumerate(album.get("content", []) or []):
            src = str(item.get("src", "") or "").strip()
            if not src:
                continue
            url = str(item.get("url", "") or "").strip()
            if not url:
                url = f"https://bkimg.cdn.bcebos.com/pic/{src}"
            title = str(item.get("title", "") or "").strip() or album_desc or f"image_{idx+1}"
            entries.append(
                {
                    "album_desc": album_desc,
                    "title": title,
                    "url": url,
                    "src": src,
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "uuid": item.get("uuid"),
                }
            )
    deduped: OrderedDict[str, Dict[str, Any]] = OrderedDict()
    for entry in entries:
        deduped.setdefault(entry["src"], entry)
    return list(deduped.values())


def save_text_files(output_dir: Path, page_data: Dict[str, Any]) -> Dict[str, Any]:
    description = str(page_data.get("description", "") or "").strip()
    lemma_title = str(page_data.get("lemmaTitle", "") or "").strip()
    card_markdown = extract_card_markdown(page_data.get("card", {}) or {})
    sections = extract_knowledge_sections(page_data)
    timeline = extract_reference_timeline(page_data)
    videos = page_data.get("modules", {}).get("videos", {}).get("data", []) or []

    overview_lines = [
        f"# {lemma_title}",
        "",
        f"来源：{page_data.get('lemmaTitle', '')}（百度百科）",
        "",
        "## 事件摘要",
        "",
        description,
        "",
        card_markdown,
        "",
        "## 目录",
        "",
    ]
    for catalog_item in page_data.get("catalog", []) or []:
        title = str(catalog_item.get("title", "") or "").strip()
        index = str(catalog_item.get("index", "") or "").strip()
        if title:
            overview_lines.append(f"- {index} {title}".strip())

    if sections:
        overview_lines.extend(["", "## 页面内可解析正文", ""])
        for section in sections:
            overview_lines.append(f"### {section['title']}")
            overview_lines.append("")
            for paragraph in section["paragraphs"]:
                overview_lines.append(paragraph)
                overview_lines.append("")

    overview_lines.extend(["", "## 视频条目说明", ""])
    if videos:
        overview_lines.append(
            "页面内存在嵌入视频，但直接下载入口受百度安全验证限制，已保存 nid/source 元数据，供后续人工补充视频文件。"
        )
    else:
        overview_lines.append("页面内未检测到嵌入视频。")

    overview_path = output_dir / "event_overview.md"
    overview_path.write_text("\n".join(overview_lines).strip() + "\n", encoding="utf-8")

    timeline_lines = []
    for item in timeline:
        date = item["date"] or "未知日期"
        site = item["site"] or "未知来源"
        title = item["title"] or "无标题"
        timeline_lines.append(f"{date}\t{site}\t{title}")
    timeline_path = output_dir / "event_timeline.txt"
    timeline_path.write_text("\n".join(timeline_lines) + "\n", encoding="utf-8")

    video_lines = []
    for idx, item in enumerate(videos, start=1):
        video_lines.append(
            f"{idx}. nid={item.get('nid')} source={item.get('source')} uuid={item.get('uuid')} title={item.get('title', '')}"
        )
    if not video_lines:
        video_lines.append("未检测到页面嵌入视频。")
    video_path = output_dir / "video_entries.txt"
    video_path.write_text("\n".join(video_lines) + "\n", encoding="utf-8")

    return {
        "sections": sections,
        "timeline": timeline,
        "videos": videos,
        "overview_path": str(overview_path),
        "timeline_path": str(timeline_path),
        "video_entries_path": str(video_path),
    }


def download_images(output_dir: Path, image_entries: List[Dict[str, Any]], user_agent: str) -> List[Dict[str, Any]]:
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for idx, entry in enumerate(image_entries, start=1):
        url = entry["url"]
        suffix = Path(urllib.parse.urlparse(url).path).suffix or ".jpg"
        file_name = f"image_{idx:02d}{suffix}"
        target = images_dir / file_name
        status = "saved"
        error = ""
        try:
            target.write_bytes(fetch_url(url, user_agent=user_agent))
        except Exception as exc:
            status = "failed"
            error = str(exc)
        saved.append(
            {
                **entry,
                "saved_path": str(target.relative_to(output_dir)),
                "status": status,
                "error": error,
            }
        )
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch a Baidu Baike event page into a LightWorld input folder.")
    parser.add_argument("--url", required=True, help="Baidu Baike page URL")
    parser.add_argument("--output-dir", required=True, help="Output folder")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    html = fetch_url(args.url, user_agent=args.user_agent).decode("utf-8", errors="ignore")
    (output_dir / "source_page.html").write_text(html, encoding="utf-8")

    page_data = extract_page_data(html)
    (output_dir / "page_data.json").write_text(
        json.dumps(page_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    text_artifacts = save_text_files(output_dir, page_data)
    image_entries = build_image_entries(page_data)
    downloaded_images = download_images(output_dir, image_entries, user_agent=args.user_agent)

    source_manifest = {
        "fetched_at": datetime.now().isoformat(),
        "source_url": args.url,
        "lemma_title": page_data.get("lemmaTitle"),
        "lemma_id": page_data.get("lemmaId"),
        "catalog": page_data.get("catalog", []),
        "downloaded_images": downloaded_images,
        "videos": page_data.get("modules", {}).get("videos", {}).get("data", []) or [],
        "notes": [
            "event_overview.md / event_timeline.txt / video_entries.txt 可直接作为 LightWorld 的文本输入。",
            "images/ 下保存了页面图册图片，可与文本一起作为 LightWorld 多模态输入。",
            "页面内嵌视频条目已抓取元数据，但未自动下载视频文件；Baidu 视频接口触发了安全验证。",
        ],
    }
    (output_dir / "source_manifest.json").write_text(
        json.dumps(source_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Saved event folder: {output_dir}")
    print(f"Overview: {text_artifacts['overview_path']}")
    print(f"Timeline: {text_artifacts['timeline_path']}")
    print(f"Video entries: {text_artifacts['video_entries_path']}")
    print(f"Images saved: {sum(1 for item in downloaded_images if item['status'] == 'saved')}/{len(downloaded_images)}")
    print(f"Videos detected: {len(source_manifest['videos'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
