"""Playwright video extractor implementation."""

from playwright.async_api import async_playwright

from webtonotion.config.logging import LoggerMixin
from webtonotion.exceptions import VideoScrapingError
from webtonotion.services.extraction.base import ExtractionData, VideoExtractor


class PlaywrightExtractor(VideoExtractor, LoggerMixin):
    """Extracts video content using Playwright."""

    def _detect_platform(self, url: str) -> str:
        """Detect platform from URL."""
        if "youtube.com" in url or "youtu.be" in url:
            return "youtube"
        elif "facebook.com" in url or "fb.watch" in url:
            return "facebook"
        elif "instagram.com" in url:
            return "instagram"
        elif "tiktok.com" in url:
            return "tiktok"
        else:
            return "unknown"

    async def _extract_title(self, page) -> str:
        """Extract title using Playwright."""
        try:
            # Try common title selectors
            selectors = ["title", "h1", '[data-testid="title"]', ".video-title"]
            for selector in selectors:
                element = await page.query_selector(selector)
                if element:
                    title = await element.text_content()
                    if title and title.strip():
                        return title.strip()
            return "Unknown Title"
        except Exception:
            return "Unknown Title"

    async def _extract_description(self, page) -> str:
        """Extract description using Playwright."""
        try:
            # Try common description selectors
            selectors = [
                'meta[name="description"]',
                ".video-description",
                '[data-testid="description"]',
            ]
            for selector in selectors:
                element = await page.query_selector(selector)
                if element:
                    if selector.startswith("meta"):
                        desc = await element.get_attribute("content")
                    else:
                        desc = await element.text_content()
                    if desc and desc.strip():
                        return desc.strip()
            return ""
        except Exception:
            return ""

    async def _extract_author(self, page) -> str:
        """Extract author using Playwright."""
        try:
            # Try common author selectors
            selectors = [".channel-name", ".author", '[data-testid="author"]', ".uploader"]
            for selector in selectors:
                element = await page.query_selector(selector)
                if element:
                    author = await element.text_content()
                    if author and author.strip():
                        return author.strip()
            return "Unknown Author"
        except Exception:
            return "Unknown Author"

    async def extract(self, url: str) -> ExtractionData:
        """Extract video content using Playwright."""
        self.logger.info(f"Using Playwright fallback for: {url}")

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                # Set user agent to avoid detection
                await page.set_extra_http_headers(
                    {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                )

                await page.goto(url, wait_until="networkidle")

                # Extract basic metadata
                title = await self._extract_title(page)
                description = await self._extract_description(page)
                author = await self._extract_author(page)

                await browser.close()

                return ExtractionData(
                    url=url,
                    title=title,
                    description=description,
                    author=author,
                    duration=None,
                    published_at=None,
                    metadata={
                        "platform": self._detect_platform(url),
                        "extraction_method": "playwright_fallback",
                    },
                    audio_path=None,
                )

        except Exception as e:
            self.logger.error(f"Playwright fallback failed for {url}: {e}")
            raise VideoScrapingError(f"Playwright fallback failed: {e}") from e
