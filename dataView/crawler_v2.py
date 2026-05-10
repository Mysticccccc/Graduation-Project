from __future__ import annotations

import hashlib
import re
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote

from django.db import transaction
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from RecruitDataVsible import settings

from .models import Company, Job


EDGE_PATH = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
PROFILE_DIR = Path(settings.BASE_DIR) / ".crawler_profile" / "zhaopin_edge"

KEYWORD_LABELS = {
    "Java开发",
    "UI设计师",
    "Web前端",
    "PHP",
    "Python",
    "Android",
    "美工",
    "深度学习",
    "算法工程师",
    "Hadoop",
    "Node.js",
    "数据开发",
    "数据分析师",
    "数据架构",
    "人工智能",
    "区块链",
    "电气工程师",
    "电子工程师",
    "PLC",
    "测试工程师",
    "设备工程师",
    "硬件工程师",
    "结构工程师",
    "工艺工程师",
    "产品经理",
    "新媒体运营",
    "运营专员",
    "淘宝运营",
    "天猫运营",
    "产品助理",
    "产品运营",
    "淘宝客服",
    "游戏运营",
    "编辑",
    "全部",
}

KEYWORD_ALIASES = {
    "Java寮€鍙?": "Java开发",
    "UI璁捐甯?": "UI设计师",
    "Web鍓嶇": "Web前端",
    "缇庡伐": "美工",
    "娣卞害瀛︿範": "深度学习",
    "绠楁硶宸ョ▼甯?": "算法工程师",
    "鏁版嵁寮€鍙?": "数据开发",
    "鏁版嵁鍒嗘瀽甯?": "数据分析师",
    "鏁版嵁鏋舵瀯": "数据架构",
    "浜哄伐鏅鸿兘": "人工智能",
    "鍖哄潡閾?": "区块链",
    "鐢垫皵宸ョ▼甯?": "电气工程师",
    "鐢靛瓙宸ョ▼甯?": "电子工程师",
    "娴嬭瘯宸ョ▼甯?": "测试工程师",
    "璁惧宸ョ▼甯?": "设备工程师",
    "纭欢宸ョ▼甯?": "硬件工程师",
    "缁撴瀯宸ョ▼甯?": "结构工程师",
    "宸ヨ壓宸ョ▼甯?": "工艺工程师",
    "浜у搧缁忕悊": "产品经理",
    "鏂板獟浣撹繍钀?": "新媒体运营",
    "杩愯惀涓撳憳": "运营专员",
    "娣樺疂杩愯惀": "淘宝运营",
    "澶╃尗杩愯惀": "天猫运营",
    "浜у搧鍔╃悊": "产品助理",
    "浜у搧杩愯惀": "产品运营",
    "娣樺疂瀹㈡湇": "淘宝客服",
    "娓告垙杩愯惀": "游戏运营",
    "缂栬緫": "编辑",
    "鍏ㄩ儴": "全部",
}

KNOWN_EDUCATION = [
    "学历不限",
    "中专",
    "大专",
    "本科",
    "硕士",
    "博士",
    "MBA",
    "EMBA",
]
KNOWN_EXPERIENCE = [
    "经验不限",
    "不限",
    "无经验",
    "1年以下",
    "1-3年",
    "3-5年",
    "5-10年",
    "10年以上",
]

SPECIAL_CITY_NAMES = ("北京", "上海", "天津", "重庆", "香港", "澳门")


class CrawlError(RuntimeError):
    pass


@dataclass
class ScrapedJob:
    company_number: str
    company_name: str
    company_logo: str
    company_website: str
    company_industry: str
    company_scale: str
    job_name: str
    post_type: str
    city: str
    job_place: str
    job_experience: str
    education: str
    min_wage: float
    max_wage: float
    job_duty: str
    job_benefits: str
    update_time: str
    source_url: str


def normalize_keyword(keyword: str) -> str:
    keyword = (keyword or "").strip()
    if keyword in KEYWORD_LABELS:
        return keyword

    if keyword in KEYWORD_ALIASES:
        return KEYWORD_ALIASES[keyword]

    decoded = unquote(keyword)
    if decoded in KEYWORD_LABELS:
        return decoded
    if decoded in KEYWORD_ALIASES:
        return KEYWORD_ALIASES[decoded]

    for label in KEYWORD_LABELS:
        if label in keyword or label in decoded:
            return label

    if "Java" in keyword or "Java" in decoded:
        return "Java开发"
    if "UI" in keyword or "UI" in decoded:
        return "UI设计师"
    if "Python" in keyword or "Python" in decoded:
        return "Python"
    if "Node" in keyword or "Node" in decoded:
        return "Node.js"
    if "Web" in keyword or "前端" in decoded:
        return "Web前端"
    return decoded or keyword or "Java开发"


@lru_cache(maxsize=1)
def _known_city_names() -> tuple[str, ...]:
    try:
        from .views import ALL_CITIES_LNG_LAT

        names = [name for name in ALL_CITIES_LNG_LAT.keys() if name and name != "其他"]
    except Exception:
        names = []

    names.extend(SPECIAL_CITY_NAMES)
    # Prefer longer city names first to avoid partial matches.
    unique_names = sorted(set(names), key=lambda value: (-len(value), value))
    return tuple(unique_names)


class ZhaopinBrowserCrawler:
    def __init__(
        self,
        log_path: str | Path,
        *,
        max_results: int = 20,
        verification_timeout: int = 180,
        page_timeout_ms: int = 60000,
    ) -> None:
        self.log_path = Path(log_path)
        self.max_results = max_results
        self.verification_timeout = verification_timeout
        self.page_timeout_ms = page_timeout_ms
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8")

    def log(self, message: str) -> None:
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def crawl(self, keyword: str) -> dict[str, object]:
        if not EDGE_PATH.exists():
            raise CrawlError(f"未找到 Edge 浏览器：{EDGE_PATH}")

        clean_keyword = normalize_keyword(keyword)
        scraped_jobs: list[ScrapedJob] = []
        self.log(f"启动新版爬虫，目标关键词：{clean_keyword}")
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                headless=False,
                executable_path=str(EDGE_PATH),
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                ],
                viewport={"width": 1440, "height": 960},
            )
            close_context = True
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://www.zhaopin.com/", wait_until="domcontentloaded", timeout=self.page_timeout_ms)
                self._wait_for_verification(page, "首页")

                if not self._try_auto_search(page, clean_keyword):
                    self.log(
                        f"未能自动触发搜索。请在弹出的 Edge 中手动搜索“{clean_keyword}”，"
                        "并保持结果页打开。程序会继续等待。"
                    )

                result_page, job_links = self._wait_for_result_page(context, page)
                self.log(f"已识别结果页：{result_page.url} | 标题：{result_page.title()}")
                if not job_links:
                    raise CrawlError("结果页中没有识别到职位链接，请检查是否仍停留在验证码页或空结果页。")

                self.log(f"识别到 {len(job_links)} 个职位链接，开始抓取详情。")
                for index, link in enumerate(job_links[: self.max_results], start=1):
                    detail_page = context.new_page()
                    try:
                        self.log(f"[{index}/{len(job_links[: self.max_results])}] 打开职位详情：{link}")
                        detail_page.goto(link, wait_until="domcontentloaded", timeout=self.page_timeout_ms)
                        self._wait_for_verification(detail_page, "职位详情页")
                        job = self._parse_job_detail(detail_page, clean_keyword, link)
                        if job:
                            scraped_jobs.append(job)
                            self.log(f"已解析职位：{job.job_name} / {job.company_name} / {job.city}")
                    finally:
                        detail_page.close()
                self.log(f"详情解析完成，已解析 {len(scraped_jobs)} 条记录，准备退出浏览器后入库。")
            except Exception as exc:
                close_context = False
                self.log(f"爬虫异常：{exc.__class__.__name__}: {exc}")
                self.log(traceback.format_exc().rstrip())
                raise
            finally:
                if close_context:
                    context.close()
                else:
                    self.log("发生异常，浏览器窗口已保留，请手动查看后再关闭。")

        self.log(f"浏览器阶段结束，开始写入数据库，共 {len(scraped_jobs)} 条记录。")
        saved = self._save_jobs(clean_keyword, scraped_jobs)
        self.log(f"抓取完成，成功入库 {saved} 条记录。")
        return {
            "keyword": clean_keyword,
            "scraped": len(scraped_jobs),
            "saved": saved,
            "log_file": self.log_path.name,
        }

    def _wait_for_verification(self, page, where: str) -> None:
        started = time.time()
        warned = False
        while time.time() - started < self.verification_timeout:
            title = page.title()
            if "Security Verification" not in title:
                return
            if not warned:
                self.log(
                    f"{where} 检测到智联安全验证。请在弹出的浏览器窗口中手动完成验证，"
                    f"程序会最多等待 {self.verification_timeout} 秒。"
                )
                warned = True
            page.wait_for_timeout(1000)
        raise CrawlError(f"{where} 长时间停留在安全验证页，未能继续抓取。")

    def _try_auto_search(self, page, keyword: str) -> bool:
        try:
            input_locator = self._find_search_input(page)
            if input_locator is None:
                return False
            input_locator.click()
            input_locator.fill("")
            input_locator.type(keyword, delay=80)
            button_locator = self._find_search_button(page)
            if button_locator is not None:
                button_locator.click()
            else:
                input_locator.press("Enter")
            self.log(f"已尝试自动搜索关键词：{keyword}")
            return True
        except Exception as exc:
            self.log(f"自动搜索失败：{exc}")
            return False

    def _find_search_input(self, page):
        candidates = page.locator("input")
        count = candidates.count()
        for index in range(count):
            node = candidates.nth(index)
            try:
                if not node.is_visible():
                    continue
                input_type = (node.get_attribute("type") or "").lower()
                placeholder = node.get_attribute("placeholder") or ""
                if input_type in {"hidden", "password", "checkbox", "radio"}:
                    continue
                if input_type in {"text", "search", ""}:
                    if any(token in placeholder for token in ("职位", "公司", "搜索")) or not placeholder:
                        return node
            except Exception:
                continue
        return None

    def _find_search_button(self, page):
        buttons = page.locator("button")
        count = buttons.count()
        for index in range(count):
            node = buttons.nth(index)
            try:
                if not node.is_visible():
                    continue
                text = (node.inner_text() or "").strip()
                if "搜索" in text:
                    return node
            except Exception:
                continue
        return None

    def _wait_for_result_page(self, context, preferred_page):
        started = time.time()
        last_snapshot = 0.0
        while time.time() - started < self.page_timeout_ms / 1000:
            for index, page in enumerate(self._ordered_pages(context, preferred_page), start=1):
                if page.is_closed():
                    continue
                if self._is_security_verification(page):
                    continue
                links = self._collect_job_links(page)
                if links:
                    return page, links

            now = time.time()
            if now - last_snapshot >= 5:
                self._log_open_pages(context, preferred_page)
                last_snapshot = now

            preferred_page.wait_for_timeout(1000)
        raise CrawlError("等待搜索结果页超时，没有识别到职位列表。")

    def _collect_job_links(self, page) -> list[str]:
        links = page.locator("a").evaluate_all(
            """
            elements => elements.map(el => ({
              href: el.href || '',
              text: (el.innerText || '').trim()
            }))
            """
        )
        results: list[str] = []
        seen = set()
        for item in links:
            href = (item.get("href") or "").strip()
            if not href:
                continue
            if "zhaopin.com" not in href:
                continue
            if not self._is_job_link(href):
                continue
            if href in seen:
                continue
            seen.add(href)
            results.append(href)
        return results

    def _ordered_pages(self, context, preferred_page):
        pages = []
        seen = set()
        for page in [preferred_page, *context.pages]:
            page_id = id(page)
            if page_id in seen:
                continue
            seen.add(page_id)
            pages.append(page)
        return pages

    def _is_security_verification(self, page) -> bool:
        try:
            return "Security Verification" in page.title()
        except Exception:
            return False

    def _log_open_pages(self, context, preferred_page) -> None:
        for index, page in enumerate(self._ordered_pages(context, preferred_page), start=1):
            if page.is_closed():
                continue
            try:
                title = page.title()
                url = page.url
                count = len(self._collect_job_links(page))
                self.log(f"检查标签页[{index}]：{title} | {url} | 识别到职位链接 {count} 个")
            except Exception as exc:
                self.log(f"检查标签页[{index}] 失败：{exc}")

    def _is_job_link(self, href: str) -> bool:
        href = href.lower()
        blocked_tokens = [
            "/companydetail/",
            "company.zhaopin.com",
            "/company/",
            "/zhaopin/",
            "/citymap",
            "/recommend",
        ]
        if any(token in href for token in blocked_tokens):
            return False

        allowed_tokens = [
            "/jobdetail/",
            "jobs.zhaopin.com/",
            "xiaoyuan.zhaopin.com/job/",
            "highpin.zhaopin.com/job/",
            "/job/",
        ]
        return any(token in href for token in allowed_tokens)

    def _parse_job_detail(self, page, keyword: str, source_url: str) -> ScrapedJob | None:
        body_text = page.locator("body").inner_text(timeout=5000)
        lines = [line.strip() for line in body_text.splitlines() if line.strip()]
        if not lines:
            return None

        title = self._first_text(page, ["h1", "h2"]) or self._guess_title_from_lines(lines)
        salary_text = self._extract_salary_text(lines)
        min_wage, max_wage = self._parse_salary(salary_text)

        location = self._extract_labeled_value(lines, ["工作地点", "上班地址", "办公地点"])
        city, job_place = self._split_location(location)

        education = self._extract_known_token(lines, KNOWN_EDUCATION) or "学历不限"
        experience = self._extract_known_token(lines, KNOWN_EXPERIENCE) or "不限"
        update_time = self._extract_datetime(lines) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        industry = self._extract_labeled_value(lines, ["所属行业", "行业", "公司行业"]) or "无定义"
        scale = self._extract_labeled_value(lines, ["公司规模", "规模"]) or "无定义"
        job_duty = self._extract_labeled_value(lines, ["工作性质", "职位性质"]) or "全职"
        job_benefits = self._extract_labeled_value(lines, ["职位福利", "公司福利", "福利待遇"]) or "无定义"

        company_website, company_name = self._extract_company_link(page, lines)
        company_number = self._extract_company_number(company_website, company_name, source_url)

        return ScrapedJob(
            company_number=company_number,
            company_name=company_name or "未知公司",
            company_logo="",
            company_website=company_website or source_url,
            company_industry=industry,
            company_scale=scale,
            job_name=title or keyword,
            post_type=keyword,
            city=city or "未知城市",
            job_place=job_place or city or "无定义",
            job_experience=experience,
            education=education,
            min_wage=min_wage,
            max_wage=max_wage,
            job_duty=job_duty,
            job_benefits=job_benefits,
            update_time=update_time,
            source_url=source_url,
        )

    def _first_text(self, page, selectors: Iterable[str]) -> str:
        for selector in selectors:
            locator = page.locator(selector)
            count = locator.count()
            for index in range(count):
                node = locator.nth(index)
                try:
                    if not node.is_visible():
                        continue
                    text = (node.inner_text() or "").strip()
                    if text and "Security Verification" not in text:
                        return text
                except Exception:
                    continue
        return ""

    def _guess_title_from_lines(self, lines: list[str]) -> str:
        skip_tokens = ["工作地点", "公司信息", "职位描述", "Security Verification"]
        for line in lines[:20]:
            if any(token in line for token in skip_tokens):
                continue
            if len(line) <= 40:
                return line
        return ""

    def _extract_salary_text(self, lines: list[str]) -> str:
        salary_re = re.compile(r"\d+(?:\.\d+)?\s*[-~至]\s*\d+(?:\.\d+)?\s*(?:K|k|千|万|元)")
        for line in lines[:40]:
            match = salary_re.search(line)
            if match:
                return match.group(0)
        return ""

    def _parse_salary(self, salary_text: str) -> tuple[float, float]:
        if not salary_text:
            return 0.0, 0.0
        match = re.search(
            r"(?P<min>\d+(?:\.\d+)?)\s*[-~至]\s*(?P<max>\d+(?:\.\d+)?)(?P<unit>\s*(?:K|k|千|万|元))",
            salary_text,
        )
        if not match:
            return 0.0, 0.0
        min_wage = float(match.group("min"))
        max_wage = float(match.group("max"))
        unit = match.group("unit").strip().lower()
        if unit == "万":
            return round(min_wage * 10, 2), round(max_wage * 10, 2)
        if unit in {"元"}:
            return round(min_wage / 1000, 2), round(max_wage / 1000, 2)
        return min_wage, max_wage

    def _extract_labeled_value(self, lines: list[str], labels: list[str]) -> str:
        for index, line in enumerate(lines):
            for label in labels:
                if line.startswith(label):
                    value = line.replace(label, "", 1).lstrip("：: ").strip()
                    if value:
                        return value
                    if index + 1 < len(lines):
                        return lines[index + 1]
        return ""

    def _extract_known_token(self, lines: list[str], tokens: list[str]) -> str:
        for line in lines[:120]:
            for token in tokens:
                if token in line:
                    return token
        return ""

    def _extract_datetime(self, lines: list[str]) -> str:
        for line in lines[:120]:
            match = re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}(?:[日 ]\s*\d{1,2}:\d{2}(?::\d{2})?)?", line)
            if match:
                value = match.group(0)
                value = value.replace("年", "-").replace("月", "-").replace("日", " ").replace("/", "-")
                return re.sub(r"\s+", " ", value).strip()
        return ""

    def _split_location(self, location: str) -> tuple[str, str]:
        if not location:
            return "", ""
        normalized = re.sub(r"\s+", "", location)

        city = self._extract_city_from_location(normalized)
        if city:
            return city, location

        parts = re.split(r"[·\-—/|,，\s]+", location)
        parts = [part for part in parts if part]
        if not parts:
            return "", location
        city = parts[0]
        if len(parts) == 1:
            return city, city
        return city, location

    def _extract_city_from_location(self, location: str) -> str:
        if "省" in location:
            location = location.split("省", 1)[1]

        best_match = ""
        best_index = None
        for city in _known_city_names():
            index = location.find(city)
            if index == -1:
                continue
            if best_index is None or index < best_index or (index == best_index and len(city) > len(best_match)):
                best_index = index
                best_match = city

        if best_match:
            return best_match

        suffix_match = re.search(r"([\u4e00-\u9fff]{2,8}?)(?:市|州|盟|地区)", location)
        if suffix_match:
            candidate = suffix_match.group(1)
            blocked_tokens = ("区", "县", "镇", "乡", "村", "路", "街", "大道", "软件园", "中心", "大厦", "公司")
            if candidate and not any(token in candidate for token in blocked_tokens):
                return candidate

        return best_match

    def _extract_company_link(self, page, lines: list[str]) -> tuple[str, str]:
        anchors = page.locator("a").evaluate_all(
            """
            elements => elements.map(el => ({
              href: el.href || '',
              text: (el.innerText || '').trim()
            }))
            """
        )
        for item in anchors:
            href = (item.get("href") or "").strip()
            text = (item.get("text") or "").strip()
            if "company.zhaopin.com" in href and text:
                return href, text

        for index, line in enumerate(lines[:50]):
            if line in {"工作地点", "职位描述", "公司信息"}:
                continue
            if "有限公司" in line or "集团" in line or "公司" in line:
                return "", line
            if index > 0 and ("有限公司" in line or "公司" in line):
                return "", line
        return "", ""

    def _extract_company_number(self, company_website: str, company_name: str, source_url: str) -> str:
        target = " ".join([company_website, source_url])
        match = re.search(r"([A-Z]{2,}\d+(?:D\d+)?)", target)
        if match:
            return match.group(1)
        seed = company_name or source_url
        digest = hashlib.md5(seed.encode("utf-8")).hexdigest()[:12].upper()
        return f"AUTO{digest}"

    def _save_jobs(self, keyword: str, jobs: list[ScrapedJob]) -> int:
        Job.objects.filter(post_type=keyword).delete()
        saved = 0
        for index, job in enumerate(jobs, start=1):
            try:
                with transaction.atomic():
                    company, _ = Company.objects.update_or_create(
                        number=job.company_number[:255],
                        defaults={
                            "company": job.company_name[:255],
                            "logo": job.company_logo[:255],
                            "website": job.company_website[:255],
                            "industry": job.company_industry[:255],
                            "scale": job.company_scale[:255],
                        },
                    )
                    Job.objects.create(
                        number=company,
                        job=job.job_name[:255],
                        post_type=job.post_type[:255],
                        city=job.city[:255],
                        job_place=job.job_place[:255],
                        job_experience=job.job_experience[:255],
                        education=job.education[:255],
                        min_wage=job.min_wage,
                        max_wage=job.max_wage,
                        job_duty=job.job_duty[:255],
                        job_benefits=job.job_benefits[:255],
                        update_time=job.update_time[:255],
                    )
                saved += 1
            except Exception as exc:
                self.log(
                    f"入库失败[{index}/{len(jobs)}]：{job.job_name[:50]} / "
                    f"{job.company_name[:50]} / {exc.__class__.__name__}: {exc}"
                )
        return saved


def crawl_keyword_to_db(keyword: str, log_path: str | Path, *, max_results: int = 20) -> dict[str, object]:
    crawler = ZhaopinBrowserCrawler(log_path=log_path, max_results=max_results)
    return crawler.crawl(keyword)
