from __future__ import annotations

import re
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class VidiqKeywordMetrics:
    volume: float | None = None
    multiplier: float | None = None
    status: str = "unavailable"
    competition_present_ignored: bool = False


@dataclass(frozen=True)
class VidiqChannelMetrics:
    available: bool = False
    views_last_30_days: int | None = None
    subscribers_last_30_days: int | None = None
    average_daily_views: int | None = None
    average_daily_subscribers: int | None = None
    raw: dict[str, str] | None = None


@dataclass(frozen=True)
class VidiqData:
    loaded: bool
    views_per_hour: float | None
    matching_terms: tuple[str, ...]
    engagement_percent: float | None = None
    outlier: str | None = None
    total_views: float | None = None
    curve_shape: str | None = None
    curve_evidence: str | None = None
    curve_metrics: dict[str, float | int | str] | None = None
    history_all_selected: bool = False
    channel_metrics: VidiqChannelMetrics = VidiqChannelMetrics()

    @property
    def still_getting_views(self) -> bool:
        return self.views_per_hour is not None and self.views_per_hour > 0

    @property
    def curve_trend(self) -> str:
        return self.curve_shape or "unconfirmed"


def _human_number(value: str) -> int | None:
    match = re.search(r"(-?[\d,.]+)\s*([KMB])?", value, re.IGNORECASE)
    if not match:
        return None
    factor = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(
        (match.group(2) or "").upper(), 1
    )
    try:
        return round(float(match.group(1).replace(",", "")) * factor)
    except ValueError:
        return None


def parse_vidiq_keyword_metrics(text: str) -> VidiqKeywordMetrics:
    """Parse VidIQ Volume/multiplier while explicitly ignoring Competition."""
    volume_match = re.search(
        r"(?:search\s+)?volume(?:\s+score)?\s*[:\n]?\s*(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    multiplier_match = re.search(
        r"(?:volume\s+)?multiplier\s*[:\n]?\s*(\d+(?:\.\d+)?)\s*x?",
        text,
        re.IGNORECASE,
    ) or re.search(
        r"(\d+(?:\.\d+)?)\s*x\s*(?:volume|search)", text, re.IGNORECASE
    )
    volume = float(volume_match.group(1)) if volume_match else None
    multiplier = float(multiplier_match.group(1)) if multiplier_match else None
    if volume is not None:
        volume = max(0.0, min(100.0, volume))
    return VidiqKeywordMetrics(
        volume=volume,
        multiplier=multiplier,
        status="collected" if volume is not None else "unavailable",
        competition_present_ignored=bool(
            re.search(r"\bcompetition\b", text, re.IGNORECASE)
        ),
    )


def extract_vidiq_keyword_metrics(sb) -> VidiqKeywordMetrics:
    """Read keyword Volume from the VidIQ search panel; Competition is never returned."""
    script = r"""
    (() => {
      const scopes = [...document.querySelectorAll(
        '#vidiq-body, [data-testid*="vidiq"], [class*="vidiq-"]'
      )].filter(node => node.getBoundingClientRect().width > 0);
      return scopes.map(node => node.innerText || '').join('\n').slice(0, 30000);
    })()
    """
    try:
        text = str(sb.cdp.evaluate(script) or "")
    except (TypeError, ValueError):
        return VidiqKeywordMetrics(status="error")
    return parse_vidiq_keyword_metrics(text)


def parse_vidiq_channel_metrics(text: str) -> VidiqChannelMetrics:
    """Parse optional VidIQ channel statistics without penalizing missing panels."""
    patterns = {
        "views_last_30_days": (
            r"(?:views|video\s+views)(?:\s+gained)?\s*(?:last|in)\s*30\s*days"
            r"\s*[:\n]?\s*([^\n]+)"
        ),
        "subscribers_last_30_days": (
            r"subscribers?(?:\s+gained)?\s*(?:last|in)\s*30\s*days"
            r"\s*[:\n]?\s*([^\n]+)"
        ),
        "average_daily_views": r"average\s+daily\s+views\s*[:\n]?\s*([^\n]+)",
        "average_daily_subscribers": (
            r"average\s+daily\s+subscribers?\s*[:\n]?\s*([^\n]+)"
        ),
    }
    parsed: dict[str, int | None] = {}
    raw: dict[str, str] = {}
    for name, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        value = match.group(1).strip() if match else ""
        parsed[name] = _human_number(value) if value else None
        if value:
            raw[name] = value
    available = any(value is not None for value in parsed.values())
    return VidiqChannelMetrics(available=available, raw=raw, **parsed)


def channel_signal(metrics: VidiqChannelMetrics) -> float:
    """Return a neutral-centred 0-100 signal; absent metrics always return 50."""
    if not metrics.available:
        return 50.0
    signals: list[float] = []
    if metrics.views_last_30_days is not None:
        views = metrics.views_last_30_days
        signals.append(80 if views >= 100_000 else 68 if views >= 20_000 else 58 if views >= 5_000 else 45)
    if metrics.subscribers_last_30_days is not None:
        subscribers = metrics.subscribers_last_30_days
        signals.append(78 if subscribers >= 1_000 else 65 if subscribers >= 200 else 55 if subscribers > 0 else 45)
    if metrics.average_daily_views is not None:
        daily = metrics.average_daily_views
        signals.append(75 if daily >= 3_000 else 62 if daily >= 500 else 52 if daily > 0 else 45)
    return sum(signals) / len(signals) if signals else 50.0


def extract_vidiq_curve(
    sb,
) -> tuple[str | None, str | None, dict[str, float | int | str]]:
    """Measure view-accumulation velocity, plateaus, accelerations, and peaks."""
    script = r"""
    (() => {
      const roots = document.querySelectorAll(
        '#vidiq-body, [data-testid*="vidiq"], [class*="vidiq-"]'
      );
      const candidates = [];
      for (const root of roots) {
        for (const path of root.querySelectorAll('svg path[d]')) {
          try {
            const length = path.getTotalLength();
            const box = path.getBBox();
            if (length < 80 || box.width < 80 || box.height < 2) continue;
            const style = getComputedStyle(path);
            const stroke = path.getAttribute('stroke') || style.stroke || '';
            const strokeWidth = parseFloat(
              path.getAttribute('stroke-width') || style.strokeWidth || '0'
            );
            const fill = path.getAttribute('fill') || style.fill || '';
            const rgb = (style.stroke.match(/\d+/g) || []).map(Number);
            const blueLike = /^#2574f5$/i.test(stroke)
              || (
                rgb.length >= 3
                && rgb[2] >= 150
                && rgb[2] >= rgb[0] + 50
                && rgb[2] >= rgb[1] + 40
              );
            const points = [];
            for (let index = 0; index <= 20; index += 1) {
              points.push(path.getPointAtLength(length * index / 20));
            }
            const monotonic = points.slice(1).filter(
              (point, index) => point.x + 1 >= points[index].x
            ).length;
            const closes = Math.abs(points[0].x - points[20].x) < box.width * 0.10;
            const lineLike = monotonic >= 18 && !closes && fill === 'none'
              && stroke !== 'none' && stroke !== 'transparent' && strokeWidth > 0;
            candidates.push({
              path, length, box, points, monotonic, lineLike, blueLike, stroke, fill
            });
          } catch (_) {}
        }
      }
      if (!candidates.length) return null;
      const lineCandidates = candidates.filter(candidate => candidate.lineLike);
      const blueLines = lineCandidates.filter(candidate => candidate.blueLike);
      const lines = blueLines.length ? blueLines : lineCandidates.filter(
        candidate => !/^(white|#fff(?:fff)?|rgb\(255,\s*255,\s*255\))$/i.test(
          candidate.stroke
        )
      );
      if (!lines.length) return {
        shape: null,
        evidence: 'no monotonic stroked VidIQ history line found'
      };
      lines.sort((a, b) => b.box.width - a.box.width || b.length - a.length);
      const selected = lines[0];
      const points = selected.points;
      const height = Math.max(1, selected.box.height);
      const gains = points.slice(1).map((point, index) =>
        Math.max(0, (points[index].y - point.y) / height)
      );
      const sum = values => values.reduce((total, value) => total + value, 0);
      const mean = values => values.length ? sum(values) / values.length : 0;
      const overall = sum(gains);
      const earlyMean = mean(gains.slice(0, 5));
      const middleMean = mean(gains.slice(5, 15));
      const recentMean = mean(gains.slice(15));
      const overallMean = mean(gains);
      const earlyShare = overall > 0 ? sum(gains.slice(0, 5)) / overall : 0;
      const recentShare = overall > 0 ? sum(gains.slice(15)) / overall : 0;
      const activeRatio = gains.filter(gain => gain > overallMean * 0.18).length / gains.length;
      const peakThreshold = Math.max(overallMean * 1.8, 0.015);
      const peakIndexes = gains.map((gain, index) => ({gain, index})).filter(
        ({gain, index}) => gain >= peakThreshold
          && gain >= (gains[index - 1] || 0)
          && gain >= (gains[index + 1] || 0)
      ).map(item => item.index);
      const separatedPeaks = peakIndexes.filter(
        (index, position) => position === 0 || index - peakIndexes[position - 1] >= 3
      );
      const recentVsMiddle = middleMean > 0 ? recentMean / middleMean : 0;
      let shape = 'dormant';
      if (overall <= 0.035 || recentMean <= 0.0005) shape = 'dormant';
      else if (
        separatedPeaks.length >= 2
        && separatedPeaks.some(index => index >= 10)
      ) shape = 'recurring peaks';
      else if (recentVsMiddle >= 1.6 && recentShare >= 0.22) {
        shape = 'recent acceleration';
      } else if (earlyShare >= 0.65 && recentMean < overallMean * 0.20) {
        shape = 'launch spike then plateau';
      } else if (activeRatio >= 0.65 && recentMean >= overallMean * 0.45) {
        shape = 'steady evergreen';
      } else if (recentMean < overallMean * 0.25) {
        shape = 'historical growth, recent plateau';
      } else {
        shape = 'decelerating growth';
      }
      const metrics = {
        overall_gain: Number(overall.toFixed(4)),
        early_share: Number(earlyShare.toFixed(4)),
        recent_share: Number(recentShare.toFixed(4)),
        early_velocity: Number(earlyMean.toFixed(4)),
        middle_velocity: Number(middleMean.toFixed(4)),
        recent_velocity: Number(recentMean.toFixed(4)),
        recent_vs_middle: Number(recentVsMiddle.toFixed(3)),
        active_segment_ratio: Number(activeRatio.toFixed(3)),
        peak_count: separatedPeaks.length,
        peak_segments: separatedPeaks.join(',')
      };
      return {
        shape,
        metrics,
        evidence: `svg shape=${shape}, overall=${overall.toFixed(3)}, ` +
          `early_share=${earlyShare.toFixed(3)}, recent_share=${recentShare.toFixed(3)}, ` +
          `velocities=${earlyMean.toFixed(4)}/${middleMean.toFixed(4)}/` +
          `${recentMean.toFixed(4)}, recent_vs_middle=${recentVsMiddle.toFixed(2)}, ` +
          `active=${activeRatio.toFixed(2)}, peaks=${separatedPeaks.join(',') || 'none'}, ` +
          `samples=${points.length}, monotonic=${selected.monotonic}/20, ` +
          `stroke=${selected.stroke}`
      };
    })()
    """
    try:
        result = sb.cdp.evaluate(script)
    except (TypeError, ValueError):
        return None, None, {}
    if not isinstance(result, dict):
        return None, None, {}
    metrics = result.get("metrics")
    return (
        result.get("shape"),
        result.get("evidence"),
        metrics if isinstance(metrics, dict) else {},
    )


def dismiss_vidiq_promotions(sb) -> int:
    """Dismiss only VIDIQ-owned promotion/onboarding UI, never YouTube controls."""
    script = """
    (() => {
      const scopes = document.querySelectorAll(
        '#vidiq-body, [data-testid*="vidiq"], [class*="vidiq-"]'
      );
      const allowed = /^(close|dismiss|no thanks|not now|maybe later|skip|got it)$/i;
      const clicked = new Set();
      let count = 0;
      for (const scope of scopes) {
        for (const el of scope.querySelectorAll(
          'button, [role="button"], [aria-label*="close" i], [aria-label*="dismiss" i]'
        )) {
          const label = (
            el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || ''
          ).trim();
          if (!allowed.test(label) || clicked.has(el)) continue;
          clicked.add(el);
          el.click();
          count += 1;
        }
      }
      return count;
    })()
    """
    try:
        return int(sb.cdp.evaluate(script) or 0)
    except (TypeError, ValueError):
        return 0


def select_vidiq_all_history(sb) -> bool:
    """Select VidIQ's All range so the curve spans release-to-present."""
    script = """
    (() => {
      const scopes = document.querySelectorAll(
        '#vidiq-body, [data-testid*="vidiq"], [class*="vidiq-"]'
      );
      const visible = node => {
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      };
      for (const scope of scopes) {
        const leaves = [...scope.querySelectorAll('p, span, div, button')]
          .filter(node => (node.innerText || '').trim() === 'All' && visible(node));
        for (const leaf of leaves) {
          let option = leaf;
          while (
            option.parentElement && option.parentElement !== scope
            && !visible(option)
          ) option = option.parentElement;
          if (!visible(option)) continue;
          option.click();
          option.dispatchEvent(new MouseEvent('click', {bubbles: true}));
          return true;
        }
      }
      return false;
    })()
    """
    try:
        selected = bool(sb.cdp.evaluate(script))
    except (TypeError, ValueError):
        return False
    if not selected:
        return False
    time.sleep(3)
    verify_script = r"""
    (() => {
      const scopes = document.querySelectorAll(
        '#vidiq-body, [data-testid*="vidiq"], [class*="vidiq-"]'
      );
      for (const scope of scopes) {
        for (const node of scope.querySelectorAll('p, span, div, button')) {
          if ((node.innerText || '').trim() !== 'All') continue;
          const indicator = node.nextElementSibling;
          if (indicator) {
            const style = getComputedStyle(indicator);
            const color = style.backgroundColor;
            const modifiedClass = String(indicator.className || '')
              .split(/\s+/).length > 1;
            if (
              modifiedClass
              || (!/rgba?\(0,\s*0,\s*0(?:,\s*0)?\)/.test(color)
                && color !== 'transparent')
            ) return true;
          }
          let option = node;
          for (let depth = 0; option && depth < 3; depth++, option = option.parentElement) {
            if (
              option.getAttribute('aria-selected') === 'true'
              || option.getAttribute('data-state') === 'active'
            ) return true;
          }
        }
      }
      return false;
    })()
    """
    try:
        return bool(sb.cdp.evaluate(verify_script))
    except (TypeError, ValueError):
        return False


def extract_vidiq(sb, timeout_seconds: int = 20) -> VidiqData:
    """Read video evidence and actual history curve; ignore volume and competition."""
    selectors = (".vidiq-score", "#vidiq-body", "[data-testid*='vidiq']", "[class*='vidiq-']")
    loaded = False
    for _ in range(max(1, timeout_seconds // 2)):
        if any(sb.cdp.is_element_visible(selector) for selector in selectors):
            loaded = True
            break
        time.sleep(2)
        sb.cdp.scroll_down(100)
    if not loaded:
        return VidiqData(False, None, ())
    source = sb.cdp.get_page_source()
    if re.search(
        r"sign\s+up\s+for\s+free\s+or\s+log\s+in\s+to\s+see\s+full\s+video\s+analytics",
        source,
        re.IGNORECASE,
    ):
        return VidiqData(False, None, (), curve_evidence="VidIQ extension login required")
    history_all_selected = select_vidiq_all_history(sb)
    source = sb.cdp.get_page_source()
    match = re.search(
        r"(?:views?\s*per\s*hour|VPH)[^0-9]{0,80}([\d,.]+)", source, re.IGNORECASE
    )
    vph = float(match.group(1).replace(",", "")) if match else None
    engagement_match = re.search(
        r"Engagement[^0-9]{0,80}([\d.]+)\s*%", source, re.IGNORECASE
    )
    engagement = float(engagement_match.group(1)) if engagement_match else None
    outlier_match = re.search(r"Outlier[^A-Za-z0-9]{0,80}([\d.]+x|N/?A)", source, re.IGNORECASE)
    outlier = outlier_match.group(1) if outlier_match else None
    total_match = re.search(
        r"([\d.]+)\s*([KMB])?[^<]{0,40}Total\s+views", source, re.IGNORECASE
    )
    total_views = None
    if total_match:
        factor = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(
            (total_match.group(2) or "").upper(), 1
        )
        total_views = float(total_match.group(1)) * factor
    terms: list[str] = []
    for selector in (
        ".vidiq-matching-terms .term",
        "[data-testid*='matching-term']",
        "[class*='matchingTerms'] [class*='term']",
    ):
        for element in sb.cdp.find_elements(selector, timeout=1):
            value = (getattr(element, "text", "") or "").strip()
            if value:
                terms.append(value)
        if terms:
            break
    curve_shape, curve_evidence, curve_metrics = extract_vidiq_curve(sb)
    channel_metrics = parse_vidiq_channel_metrics(source)
    return VidiqData(
        True,
        vph,
        tuple(dict.fromkeys(terms)),
        engagement_percent=engagement,
        outlier=outlier,
        total_views=total_views,
        curve_shape=curve_shape,
        curve_evidence=curve_evidence,
        curve_metrics=curve_metrics,
        history_all_selected=history_all_selected,
        channel_metrics=channel_metrics,
    )
