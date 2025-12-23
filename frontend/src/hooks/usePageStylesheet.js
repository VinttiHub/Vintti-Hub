import { useEffect } from 'react';

export default function usePageStylesheet(href) {
  useEffect(() => {
    if (!href) return undefined;
    const existing = document.querySelector(`link[data-dynamic-style="${href}"]`);
    if (existing) return undefined;

    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    link.dataset.dynamicStyle = href;
    document.head.appendChild(link);

    return () => {
      if (link.parentNode) {
        link.parentNode.removeChild(link);
      }
    };
  }, [href]);
}
