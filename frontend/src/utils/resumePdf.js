import { PDFDocument, StandardFonts, rgb } from 'pdf-lib';

const PAGE_MARGIN = 40;
const BODY_FONT_SIZE = 11;
const HEADING_FONT_SIZE = 14;
const TITLE_FONT_SIZE = 22;
const SECTION_SPACING = 12;

function parseJsonArray(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      console.warn('Unable to parse resume field', err);
      return [];
    }
  }
  return [];
}

function cleanHtml(value) {
  if (!value || typeof value !== 'string') return '';
  if (typeof window === 'undefined' || !window.document) {
    return value.replace(/<[^>]+>/g, ' ');
  }
  const div = window.document.createElement('div');
  div.innerHTML = value;
  return div.textContent ? div.textContent.replace(/\s+/g, ' ').trim() : '';
}

function extractListItems(html) {
  if (!html || typeof html !== 'string') return [];
  if (typeof window === 'undefined' || !window.document) return [];
  const div = window.document.createElement('div');
  div.innerHTML = html;
  return Array.from(div.querySelectorAll('li'))
    .map((li) => li.textContent.trim())
    .filter(Boolean);
}

function formatDatePart(part) {
  if (!part) return null;
  const [year, month] = part.split('-');
  if (!year) return null;
  const date = month ? new Date(`${year}-${month}-01T12:00:00Z`) : new Date(`${year}-01-01T12:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString('en', { year: 'numeric', month: 'short' });
}

function formatDateRange(exp) {
  const start = formatDatePart(exp.start_date);
  const end = exp.current ? 'Present' : formatDatePart(exp.end_date);
  if (!start && !end) return '';
  if (start && end) return `${start} – ${end}`;
  if (start) return `${start} – Present`;
  return end || '';
}

function normalizeResume(rawResume = {}) {
  const workExperience = parseJsonArray(rawResume.work_experience).map((item) => ({
    title: item?.title || '',
    company: item?.company || '',
    location: item?.location || item?.country || '',
    start_date: item?.start_date || '',
    end_date: item?.end_date || '',
    current: Boolean(item?.current),
    summary: cleanHtml(item?.description || item?.description_html || ''),
    bullets: extractListItems(item?.description || item?.description_html || ''),
  }));

  const education = parseJsonArray(rawResume.education).map((item) => ({
    degree: item?.degree || item?.title || '',
    school: item?.institution || item?.company || '',
    location: item?.location || item?.country || '',
    start_date: item?.start_date || '',
    end_date: item?.end_date || '',
    summary: cleanHtml(item?.description || ''),
  }));

  const tools = parseJsonArray(rawResume.tools).map((tool) => {
    if (typeof tool === 'string') return { name: tool, level: '' };
    return { name: tool?.tool || tool?.name || '', level: tool?.level || '' };
  });

  const languages = parseJsonArray(rawResume.languages).map((lang) => ({
    name: lang?.language || lang?.name || '',
    level: lang?.level || '',
  }));

  return {
    about: cleanHtml(rawResume.about),
    videoLink: rawResume.video_link || '',
    workExperience,
    education,
    tools,
    languages,
  };
}

function createDownloader(bytes, filename) {
  const blob = new Blob([bytes], { type: 'application/pdf' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export async function downloadResumePdf({ candidate, resume }) {
  if (!resume) throw new Error('Missing resume data');
  const normalized = normalizeResume(resume);
  const pdfDoc = await PDFDocument.create();
  const regularFont = await pdfDoc.embedFont(StandardFonts.Helvetica);
  const boldFont = await pdfDoc.embedFont(StandardFonts.HelveticaBold);

  let page = pdfDoc.addPage();
  let { width, height } = page.getSize();
  const usableWidth = width - PAGE_MARGIN * 2;
  let cursorY = height - PAGE_MARGIN;

  const ensureSpace = (neededHeight) => {
    if (cursorY - neededHeight <= PAGE_MARGIN) {
      page = pdfDoc.addPage();
      ({ width, height } = page.getSize());
      cursorY = height - PAGE_MARGIN;
    }
  };

  const drawLine = (text, { font = regularFont, size = BODY_FONT_SIZE, color = rgb(0.15, 0.15, 0.17), indent = 0 }) => {
    if (!text) return;
    const lineHeight = size + 2;
    ensureSpace(lineHeight);
    page.drawText(text, { x: PAGE_MARGIN + indent, y: cursorY - lineHeight, font, size, color });
    cursorY -= lineHeight;
  };

  const addParagraph = (text, options = {}) => {
    const content = text ? text.toString().trim() : '';
    if (!content) return;
    const { font = regularFont, size = BODY_FONT_SIZE, indent = 0, spacing = 4, color = rgb(0.15, 0.15, 0.17) } = options;
    const words = content.split(/\s+/);
    const availableWidth = usableWidth - indent;
    const lineHeight = size + 2;
    let currentLine = '';
    words.forEach((word) => {
      const nextLine = currentLine ? `${currentLine} ${word}` : word;
      const textWidth = font.widthOfTextAtSize(nextLine, size);
      if (textWidth > availableWidth && currentLine) {
        drawLine(currentLine, { font, size, indent, color });
        currentLine = word;
      } else {
        currentLine = nextLine;
      }
    });
    if (currentLine) {
      drawLine(currentLine, { font, size, indent, color });
    }
    cursorY -= spacing;
  };

  const addHeading = (text) => {
    if (!text) return;
    cursorY -= SECTION_SPACING / 2;
    drawLine(text, { font: boldFont, size: HEADING_FONT_SIZE });
    cursorY -= SECTION_SPACING / 2;
  };

  const addDivider = () => {
    ensureSpace(6);
    page.drawLine({
      start: { x: PAGE_MARGIN, y: cursorY - 4 },
      end: { x: width - PAGE_MARGIN, y: cursorY - 4 },
      thickness: 0.5,
      color: rgb(0.8, 0.8, 0.8),
    });
    cursorY -= 8;
  };

  const addList = (items, bullet = '•') => {
    if (!items || !items.length) return;
    items.forEach((item) => {
      addParagraph(`${bullet} ${item}`, { indent: 10 });
    });
  };

  const metaBits = [candidate?.country, candidate?.timezone, candidate?.english_level]
    .map((bit) => (bit || '').toString().trim())
    .filter(Boolean);

  drawLine('Vintti · Top Candidate Profile', { font: boldFont, size: 10, color: rgb(0.4, 0.4, 0.4) });
  cursorY -= 6;
  const candidateName = candidate?.name || 'Candidate';
  drawLine(candidateName, { font: boldFont, size: TITLE_FONT_SIZE });
  if (metaBits.length) {
    addParagraph(metaBits.join(' • '));
  }
  addDivider();

  if (normalized.about) {
    addHeading('About');
    addParagraph(normalized.about);
  }

  if (normalized.workExperience.length) {
    addHeading('Work Experience');
    normalized.workExperience.forEach((exp, index) => {
      const titleLine = [exp.title, exp.company].filter(Boolean).join(' · ');
      addParagraph(titleLine, { font: boldFont });
      const detailLine = [formatDateRange(exp), exp.location].filter(Boolean).join(' • ');
      if (detailLine) {
        addParagraph(detailLine, { size: BODY_FONT_SIZE - 1, color: rgb(0.35, 0.35, 0.35) });
      }
      if (exp.summary) {
        addParagraph(exp.summary);
      }
      addList(exp.bullets);
      if (index < normalized.workExperience.length - 1) {
        cursorY -= 6;
      }
    });
  }

  if (normalized.education.length) {
    addHeading('Education');
    normalized.education.forEach((edu, index) => {
      addParagraph([edu.degree, edu.school].filter(Boolean).join(' · '), { font: boldFont });
      const detailLine = [formatDateRange(edu), edu.location].filter(Boolean).join(' • ');
      if (detailLine) {
        addParagraph(detailLine, { size: BODY_FONT_SIZE - 1, color: rgb(0.35, 0.35, 0.35) });
      }
      if (edu.summary) {
        addParagraph(edu.summary);
      }
      if (index < normalized.education.length - 1) {
        cursorY -= 4;
      }
    });
  }

  if (normalized.tools.length) {
    addHeading('Tools');
    normalized.tools.forEach((tool) => {
      const label = tool.level ? `${tool.name} — ${tool.level}` : tool.name;
      addParagraph(label);
    });
  }

  if (normalized.languages.length) {
    addHeading('Languages');
    normalized.languages.forEach((lang) => {
      const label = lang.level ? `${lang.name} — ${lang.level}` : lang.name;
      addParagraph(label);
    });
  }

  if (normalized.videoLink) {
    addHeading('Video Introduction');
    addParagraph(normalized.videoLink);
  }

  const pdfBytes = await pdfDoc.save();
  const fileNameBase = candidateName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'resume';
  createDownloader(pdfBytes, `${fileNameBase}-resume.pdf`);
}

export default downloadResumePdf;
