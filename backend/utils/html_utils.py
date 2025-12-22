import html as _html
import re

_ALLOWED_TAGS = ('p', 'ul', 'ol', 'li', 'br', 'b', 'strong', 'i', 'em', 'a')


def _strip_attrs_keep_href(tag_html: str) -> str:
    """
    Return sanitized tag with attributes removed except for <a href="...">.
    """
    tag = tag_html
    match = re.match(r'<\s*([a-z0-9]+)(\s[^>]*)?>', tag, flags=re.I)
    if not match:
        return tag

    name = match.group(1).lower()
    if name == 'a':
        href_match = re.search(r'href="([^"]*)"', tag, flags=re.I)
        href = href_match.group(1).strip() if href_match else ''
        if href and href.lower().startswith(('http://', 'https://', 'mailto:')):
            return f'<a href="{href}">'
        return '<a>'
    if name in _ALLOWED_TAGS:
        return f'<{name}>'
    return tag


def clean_html_for_webflow(value: str, output: str = 'html') -> str:
    """
    Sanitize noisy HTML (Webflow/Greenhouse/etc.) leaving a safe subset.
    """
    if not value:
        return ""

    s = _html.unescape(str(value))
    s = s.replace('\u00A0', ' ').replace('&nbsp;', ' ')
    s = re.sub(r'<\s*(script|style)[^>]*>.*?</\s*\1\s*>', '', s, flags=re.I | re.S)
    s = re.sub(r'<ul[^>]*class="[^"]*(?:list---|discList---)[^"]*"[^>]*>', '<ul>', s, flags=re.I)
    s = re.sub(r'<ol[^>]*class="[^"]*list---[^"]*"[^>]*>', '<ol>', s, flags=re.I)
    s = re.sub(r'<li[^>]*class="[^"]*"[^>]*>', '<li>', s, flags=re.I)
    s = re.sub(r'<\s*div[^>]*>', '<p>', s, flags=re.I)
    s = re.sub(r'</\s*div\s*>', '</p>', s, flags=re.I)
    s = re.sub(r'<\s*span[^>]*>', '', s, flags=re.I)
    s = re.sub(r'</\s*span\s*>', '', s, flags=re.I)
    s = re.sub(r'\sstyle="[^"]*"', '', s, flags=re.I)
    s = re.sub(r'\sclass="[^"]*"', '', s, flags=re.I)
    s = re.sub(r'\sid="[^"]*"', '', s, flags=re.I)
    s = re.sub(r'\sdata-[a-z0-9_-]+="[^"]*"', '', s, flags=re.I)
    s = re.sub(r'\son[a-z]+\s*=\s*"[^"]*"', '', s, flags=re.I)
    s = re.sub(r'<a[^>]*>', _strip_attrs_keep_href, s, flags=re.I)

    def _whitelist_tags(match):
        tag = match.group(1).lower()
        if tag in _ALLOWED_TAGS:
            full = match.group(0)
            if full.strip().startswith('</'):
                return f'</{tag}>'
            return _strip_attrs_keep_href(f'<{tag}>')
        return ''

    s = re.sub(r'</?([a-z0-9]+)(\s[^>]*)?>', _whitelist_tags, s, flags=re.I)
    s = re.sub(r'<p>\s*(<br\s*/?>)?\s*</p>', '', s, flags=re.I)
    s = re.sub(r'<li>\s*</li>', '', s, flags=re.I)
    s = re.sub(r'(<br\s*/?>\s*){2,}', '<br>', s, flags=re.I)
    s = re.sub(r'[ \t]{2,}', ' ', s).strip()

    if output == 'text':
        tmp = s
        tmp = re.sub(r'\s*<li>\s*', '- ', tmp, flags=re.I)
        tmp = re.sub(r'\s*</li>\s*', '\n', tmp, flags=re.I)
        tmp = re.sub(r'\s*</p>\s*', '\n', tmp, flags=re.I)
        tmp = re.sub(r'\s*<br\s*/?>\s*', '\n', tmp, flags=re.I)
        tmp = re.sub(r'</?(p|ul|ol|strong|b|em|i)>', '', tmp, flags=re.I)
        tmp = re.sub(r'<a href="([^"]*)">([^<]*)</a>', r'\2 (\1)', tmp, flags=re.I)
        tmp = re.sub(r'</?[^>]+>', '', tmp)
        lines = [ln.strip() for ln in tmp.splitlines()]
        return '\n'.join([ln for ln in lines if ln])

    return s


__all__ = ["clean_html_for_webflow"]
