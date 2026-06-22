import html as _html
import re

_ALLOWED_TAGS = ('p', 'ul', 'ol', 'li', 'br', 'b', 'strong', 'i', 'em', 'a')


def _strip_attrs_keep_href(tag_html: str) -> str:
    """
    Return sanitized tag with attributes removed except for <a href="...">.
    """
    tag = tag_html.group(0) if hasattr(tag_html, 'group') else tag_html
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


def clean_job_description_html(value: str) -> str:
    """
    Clean JD HTML and repair common broken rich-text structure.
    """
    s = clean_html_for_webflow(value, output='html')
    if not s:
        return ''

    def text_only(fragment: str) -> str:
        text = re.sub(r'<[^>]+>', '', fragment or '')
        return re.sub(r'\s+', ' ', _html.unescape(text)).strip()

    def looks_like_heading(text: str) -> bool:
        lower = (text or '').strip().lower()
        if not lower:
            return False
        if ',' in lower or len(lower) > 60:
            return False
        heading_words = (
            'overview', 'summary', 'responsibilities', 'requirements',
            'qualifications', 'benefits', 'compensation', 'schedule',
            'location', 'tools', 'nice to have', 'nice-to-have',
            'must have', 'must-have', 'what you', 'who you', 'your qualifications',
            'your requirements', 'your responsibilities',
        )
        return any(lower == word or lower.startswith(f'{word}:') or lower.startswith(f'{word} (') for word in heading_words)

    split_heading_re = re.compile(
        r'<p>\s*(?P<prefix>(?:[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+\s*)?(?:main|key|core|primary|general|job|role|required|preferred|additional|nice to|nice-to|must|what you|what you’ll|what we|what we’re|who you|your))\s*</p>\s*'
        r'<p>\s*(?:<strong>|<b>)?\s*(?P<tail>responsibilities|requirements|qualifications|skills|duties|tasks|overview|summary|information|haves?|to haves?|do|bring|are|looking for|work with)\s*(?:</strong>|</b>)?\s*</p>',
        flags=re.I | re.S,
    )

    def merge_split_heading(match):
        prefix = text_only(match.group('prefix'))
        tail = text_only(match.group('tail'))
        if not prefix or not tail:
            return match.group(0)
        return f'<p><strong>{prefix} {tail}</strong></p>'

    s = split_heading_re.sub(merge_split_heading, s)

    def looks_open(text: str) -> bool:
        clean = (text or '').strip()
        if not clean:
            return False
        if not re.search(r'[.!?;:]$', clean):
            return True
        return bool(re.search(
            r'\b(and|or|with|including|such as|like|in|of|for|to|from|between|using|across|plus|via|through|within|without|by|as|on|at)$',
            clean,
            flags=re.I,
        ))

    def looks_like_continuation(text: str) -> bool:
        clean = (text or '').strip()
        if not clean or looks_like_heading(clean):
            return False
        return bool(
            re.match(r'^[a-z0-9(]', clean)
            or re.match(r'^(and|or|with|including|such as|like|plus|via|through|within|without|by|as|on|at)\b', clean, flags=re.I)
            or re.match(r'^[A-Z][A-Za-z0-9+/#.&-]*(,|\s+(and|or|with)\b|\s+[a-z])', clean)
        )

    orphan_after_list_re = re.compile(
        r'<li>(?P<li>(?:(?!</li>).)*)</li>\s*</ul>\s*<p>\s*(?P<p>(?:<(?:strong|b)>.*?</(?:strong|b)>|[^<]+))\s*</p>\s*<ul>',
        flags=re.I | re.S,
    )

    def merge_orphan(match):
        li_html = match.group('li')
        p_html = match.group('p')
        li_text = text_only(li_html)
        p_text = text_only(p_html)
        if looks_open(li_text) and looks_like_continuation(p_text):
            return f'<li>{li_html} {p_text}</li>'
        return match.group(0)

    previous = None
    while previous != s:
        previous = s
        s = orphan_after_list_re.sub(merge_orphan, s)

    # Inline bold in list items is usually accidental from pasted/generated JDs.
    s = re.sub(
        r'<li>(?P<body>.*?)</li>',
        lambda m: '<li>' + re.sub(r'</?(strong|b|em|i)>', '', m.group('body'), flags=re.I) + '</li>',
        s,
        flags=re.I | re.S,
    )

    return re.sub(r'[ \t]{2,}', ' ', s).strip()


__all__ = ["clean_html_for_webflow", "clean_job_description_html"]
