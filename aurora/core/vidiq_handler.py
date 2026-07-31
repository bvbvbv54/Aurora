from __future__ import annotations

import re
import time
from dataclasses import dataclass


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
    history_all_selected: bool = False

    @property
    def still_getting_views(self) -> bool:
        return self.views_per_hour is not None and self.views_per_hour > 0

    @property
    def curve_trend(self) -> str:
        return self.curve_shape or "unconfirmed"


def extract_vidiq_curve(sb) -> tuple[str | None, str | None]:
    """Read the actual right-side vidIQ SVG history curve; no volume/competition fields."""
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
      const overall = (points[0].y - points[20].y) / height;
      const recent = (points[15].y - points[20].y) / height;
      let shape = 'flat';
      if (overall > 0.20 && recent > 0.02) shape = 'increasing';
      else if (overall > 0.20 && recent >= -0.02) shape = 'historical growth, recent plateau';
      else if (overall < -0.15) shape = 'declining';
      else if (recent > 0.05) shape = 'recently increasing';
      return {
        shape,
        evidence: `svg overall=${overall.toFixed(3)}, recent=${recent.toFixed(3)}, ` +
          `samples=${points.length}, monotonic=${selected.monotonic}/20, ` +
          `stroke=${selected.stroke}`
      };
    })()
    """
    try:
        result = sb.cdp.evaluate(script)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(result, dict):
        return None, None
    return result.get("shape"), result.get("evidence")


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
    curve_shape, curve_evidence = extract_vidiq_curve(sb)
    return VidiqData(
        True,
        vph,
        tuple(dict.fromkeys(terms)),
        engagement_percent=engagement,
        outlier=outlier,
        total_views=total_views,
        curve_shape=curve_shape,
        curve_evidence=curve_evidence,
        history_all_selected=history_all_selected,
    )
