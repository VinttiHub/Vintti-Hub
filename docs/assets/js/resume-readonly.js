document.addEventListener("DOMContentLoaded", async () => {
  const urlParams = new URLSearchParams(window.location.search);
  const candidateId = urlParams.get("id");
  const isPdfExport = urlParams.has("pdf_export");
  const bodyEl = document.body;
  if (bodyEl) bodyEl.dataset.resumeReady = "loading";

  if (isPdfExport) {
    document.documentElement.style.backgroundColor = "#fff";
    if (bodyEl) {
      bodyEl.style.backgroundColor = "#fff";
      bodyEl.style.paddingTop = "32px";
      bodyEl.style.paddingBottom = "48px";
      const watermarkLayer = document.createElement("div");
      Object.assign(watermarkLayer.style, {
        position: "fixed",
        inset: "0",
        pointerEvents: "none",
        zIndex: "0",
        opacity: "0.08",
        mixBlendMode: "multiply",
      });
      const svgMarkup = `
        <svg xmlns="http://www.w3.org/2000/svg" width="500" height="500" viewBox="0 0 500 500">
          <text x="-50" y="300" fill="rgba(0,59,255,0.45)" font-size="120" font-family="Onest, sans-serif" font-weight="700" transform="rotate(-30 0 250)">
            VINTTI
          </text>
        </svg>`;
      watermarkLayer.style.backgroundImage = `url("data:image/svg+xml,${encodeURIComponent(svgMarkup)}")`;
      watermarkLayer.style.backgroundRepeat = "repeat";
      watermarkLayer.style.backgroundSize = "520px 520px";
      watermarkLayer.style.transform = "translateZ(0)";
      bodyEl.appendChild(watermarkLayer);
    }
    const header = document.querySelector(".cv-header");
    if (header) header.remove();
    const footer = document.querySelector(".cv-footer");
    if (footer) footer.remove();
    const container = document.querySelector(".cv-container");
    if (container) {
      container.style.position = "relative";
      container.style.zIndex = "5";
    }
  }

  const notifyParent = (status) => {
    if (bodyEl) {
      bodyEl.dataset.resumeReady = status ? "ready" : "error";
    }
    if (window.parent && window.parent !== window) {
      try {
        window.parent.postMessage(
          {
            source: "resume-readonly",
            type: "resume-readonly-ready",
            status: status ? "ready" : "error",
            candidateId,
          },
          "*",
        );
      } catch (err) {
        console.warn("Unable to notify parent about resume readiness", err);
      }
    }
  };
// Muestra esto cuando no hay fecha
const NO_DATE_LABEL = "No date assigned";

function formatDate(dateStr) {
  // Acepta "YYYY-MM" o "YYYY-MM-DD". Si falta algo, devolvemos el label.
  if (!dateStr || typeof dateStr !== "string") return NO_DATE_LABEL;
  const [year, month] = dateStr.split("-");
  if (!year || !month) return NO_DATE_LABEL;

  const date = new Date(`${year}-${month}-01T12:00:00Z`); // día seguro en UTC
  if (isNaN(date.getTime())) return NO_DATE_LABEL;

  return date.toLocaleDateString("en-US", { year: "numeric", month: "short" });
}

function formatDateFromDateObj(d) {
  if (!d || !(d instanceof Date) || isNaN(d.getTime())) return NO_DATE_LABEL;
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short" });
}


  if (!candidateId) {
    console.error("❌ Candidate ID missing in URL");
    notifyParent(false);
    return;
  }

  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/resumes/${candidateId}`);
    const data = await res.json();
    console.log("📦 Resume completo recibido:", data);

    // Logs individuales por sección
    console.log("🧠 About:", data.about);
    console.log("🎓 Education:", data.education);
    console.log("💼 Work Experience:", data.work_experience);
    console.log("🛠️ Tools:", data.tools);
    console.log("📹 Video Link:", data.video_link);
    // Nombre del candidato (fetch adicional)
    const nameRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`);
    const nameData = await nameRes.json();
    document.getElementById("candidateNameTitle").textContent = nameData.name || "Unnamed Candidate";
    document.getElementById("candidateCountry").textContent = nameData.country || "—";

    // 🧠 About
// 🧠 About
const aboutP = document.getElementById("aboutField");
aboutP.innerHTML = data.about || "—";
cleanInlineStyles(aboutP);


// 💼 Work Experience
// 💼 Work Experience (LinkedIn-like multi-roles)
const workExperienceList = document.getElementById("workExperienceList");

workExperienceList.classList.add("timeline");

let workExperience = [];
try {
  workExperience = JSON.parse(data.work_experience || "[]");
} catch (e) {
  console.error("❌ Error parsing work_experience:", e);
}

/* Helpers locales */
function safeDate(d) {
  try { return d ? new Date(d) : null; } catch { return null; }
}
function extractMultiRoles(exp) {
  if (!exp || !exp.description) return null;

  const wrapper = document.createElement("div");
  wrapper.innerHTML = exp.description;

  const pack = wrapper.querySelector('.mr-pack[data-type="multi-roles"]');
  if (!pack) return null;

  // 1) Primero intentamos con data-roles (url-encoded JSON)
  let roles = [];
  const rolesAttr = pack.getAttribute("data-roles");
  if (rolesAttr) {
    try {
      roles = JSON.parse(decodeURIComponent(rolesAttr));
    } catch (err) {
      console.warn("⚠️ data-roles inválido:", err);
    }
  }

  // 2) Si no vino data-roles, caemos al DOM (.mr-item)
  if (!roles.length) {
    pack.querySelectorAll(".mr-item").forEach((item) => {
      roles.push({
        title: (item.querySelector(".mr-title-txt")?.textContent || "").trim(),
        start_date: item.getAttribute("data-start") || "",
        end_date: item.getAttribute("data-end") || "",
        current: false,
        description_html: item.querySelector(".mr-desc-html")?.innerHTML || "",
      });
    });
  }

  // Normalizamos y ordenamos (más reciente primero por end_date o current)
  roles = roles
    .map((r) => ({
      title: r.title || "",
      start_date: r.start_date || "",
      end_date: r.current ? "" : (r.end_date || ""),
      current: !!r.current,
      description_html: r.description_html || "",
    }))
    .sort((a, b) => {
      const aEnd = a.current || !a.end_date ? new Date(2100, 0, 1) : new Date(a.end_date);
      const bEnd = b.current || !b.end_date ? new Date(2100, 0, 1) : new Date(b.end_date);
      return bEnd - aEnd;
    });

  return roles;
}

function renderExperienceEntry(exp) {
  const roles = extractMultiRoles(exp);

  // ---------- CASO SIMPLE: 0 o 1 rol ----------
  if (!roles || roles.length <= 1) {
    const startDate = formatDate(exp.start_date);
    const endDate = exp.current ? "Present" : formatDate(exp.end_date);
    const locationText = exp.location || exp.country || "";

    const entry = document.createElement("div");
    entry.className = "cv-entry";

    const left = document.createElement("div");
    left.className = "cv-entry-left";

    const dateDiv = document.createElement("div");
    dateDiv.className = "cv-entry-date";
    dateDiv.textContent = `${startDate} – ${endDate}`;
    left.appendChild(dateDiv);

    if (locationText) {
      const locDiv = document.createElement("div");
      locDiv.className = "cv-entry-location";
      locDiv.textContent = locationText;
      left.appendChild(locDiv);
    }

    const right = document.createElement("div");
    right.className = "cv-entry-right";

    const roleDiv = document.createElement("div");
    roleDiv.className = "cv-entry-role";
    roleDiv.textContent = exp.title || "—";

    const companyDiv = document.createElement("div");
    companyDiv.className = "cv-entry-company";
    companyDiv.textContent = exp.company || "—";

    const summaryDiv = document.createElement("div");
    summaryDiv.className = "cv-entry-summary resume-description";
    summaryDiv.innerHTML = cleanHTML(exp.description || "");

    right.appendChild(roleDiv);
    right.appendChild(companyDiv);
    right.appendChild(summaryDiv);

    entry.appendChild(left);
    entry.appendChild(right);
    return entry;
  }

  // ---------- CASO MULTI-ROLES (misma empresa, varios cargos) ----------
  const hasCurrent = roles.some((r) => r.current);
  const overallStart = roles.reduce((min, r) => {
    const d = safeDate(r.start_date);
    return (!min || (d && d < min)) ? d : min;
  }, null);
  const overallEnd = hasCurrent
    ? null
    : roles.reduce((max, r) => {
        const d = safeDate(r.end_date);
        return (!max || (d && d > max)) ? d : max;
      }, null);

  const entry = document.createElement("div");
  entry.className = "cv-entry multi-company";

  const left = document.createElement("div");
  left.className = "cv-entry-left";

  const dateDiv = document.createElement("div");
  dateDiv.className = "cv-entry-date";
  dateDiv.textContent = `${formatDateFromDateObj(overallStart)} – ${
    overallEnd ? formatDateFromDateObj(overallEnd) : "Present"
  }`;
  left.appendChild(dateDiv);

  const locationText = exp.location || exp.country || "";
  if (locationText) {
    const locDiv = document.createElement("div");
    locDiv.className = "cv-entry-location";
    locDiv.textContent = locationText;
    left.appendChild(locDiv);
  }

  const right = document.createElement("div");
  right.className = "cv-entry-right";

  const companyDiv = document.createElement("div");
  companyDiv.className = "cv-entry-company";
  companyDiv.textContent = exp.company || "—";
  right.appendChild(companyDiv);

  const rolesContainer = document.createElement("div");
  rolesContainer.className = "multi-timeline";

  roles.forEach((r) => {
    const roleBlock = document.createElement("div");
    roleBlock.className = "multi-role";

    const titleDiv = document.createElement("div");
    titleDiv.className = "cv-entry-role";
    titleDiv.textContent = r.title || "—";

    const datesDiv = document.createElement("div");
    datesDiv.className = "multi-dates";
    const sd = formatDate(r.start_date);
    const ed = r.current ? "Present" : formatDate(r.end_date);
    datesDiv.textContent = `${sd} – ${ed}`;

    roleBlock.appendChild(titleDiv);
    roleBlock.appendChild(datesDiv);

    if (r.description_html) {
      const descDiv = document.createElement("div");
      descDiv.className = "multi-desc";
      descDiv.innerHTML = cleanHTML(r.description_html);
      roleBlock.appendChild(descDiv);
    }

    rolesContainer.appendChild(roleBlock);
  });

  right.appendChild(rolesContainer);
  entry.appendChild(left);
  entry.appendChild(right);

  return entry;
}


/* Pintamos la experiencia (orden existente por fin de contrato) */
sortByEndDateDescending(workExperience).forEach((exp) => {
  workExperienceList.appendChild(renderExperienceEntry(exp));
});

// 🎓 Education
const educationList = document.getElementById("educationList");

  educationList.classList.add("timeline");

  let education = [];
  try {
    education = JSON.parse(data.education || "[]");
  } catch (e) {
    console.error("❌ Error parsing education:", e);
  }
  if (education.length === 0) {
    document.getElementById("educationSection").style.display = "none";
  } else {
    sortByEndDateDescending(education).forEach((edu) => {
    const startDate = formatDate(edu.start_date);
    const endDate = edu.current ? "Present" : formatDate(edu.end_date);

    const entry = document.createElement("div");
    entry.className = "cv-entry";

    const left = document.createElement("div");
    left.className = "cv-entry-left";

    const dateDiv = document.createElement("div");
    dateDiv.className = "cv-entry-date";
    dateDiv.textContent = `${startDate} – ${endDate}`;
    left.appendChild(dateDiv);

    if (edu.country && edu.country.trim()) {
      const locDiv = document.createElement("div");
      locDiv.className = "cv-entry-location";
      locDiv.textContent = `${getFlagEmoji(edu.country)} ${edu.country}`.trim();
      left.appendChild(locDiv);
    }

    const right = document.createElement("div");
    right.className = "cv-entry-right";

    const titleDiv = document.createElement("div");
    titleDiv.className = "cv-entry-role";
    titleDiv.textContent = edu.title || "—";

    const instDiv = document.createElement("div");
    instDiv.className = "cv-entry-company";
    instDiv.textContent = edu.institution || "—";

    right.appendChild(titleDiv);
    right.appendChild(instDiv);

    if (edu.description) {
      const descDiv = document.createElement("div");
      descDiv.className = "cv-entry-summary resume-description";
      descDiv.innerHTML = cleanHTML(edu.description);
      right.appendChild(descDiv);
    }

    entry.appendChild(left);
    entry.appendChild(right);
    educationList.appendChild(entry);

});
}

function createDots(level, mapping, maxDots) {
  const count = mapping[level] || 0;
  let html = "";
  for (let i = 1; i <= maxDots; i++) {
    html += `<span class="level-dot ${i <= count ? "filled" : ""}"></span>`;
  }
  return html;
}

const TOOL_LEVEL_MAP = {
  Basic: 1,
  Intermediate: 2,
  Advanced: 3,
};

const LANGUAGE_LEVEL_MAP = {
  Basic: 1,
  Regular: 2,
  Fluent: 3,
  Native: 4,
};


// 🛠️ Tools
const toolsList = document.getElementById("toolsList");
let tools = [];
try {
  tools = JSON.parse(data.tools || "[]");
} catch (e) {
  console.error("❌ Error parsing tools:", e);
}

if (tools.length === 0) {
  document.getElementById("toolsSection").style.display = "none";
} else {
  toolsList.innerHTML = "";
  tools.forEach((tool) => {
    const row = document.createElement("div");
    row.className = "skill-row";

    const name = typeof tool === "object" ? tool.tool : tool;
    const level = typeof tool === "object" && tool.level ? tool.level : "";

    row.innerHTML = `
      <div class="skill-name">${name}</div>
      <div class="skill-level">${level}</div>
      <div class="skill-dots">
        ${createDots(level, TOOL_LEVEL_MAP, 3)}
      </div>
    `;

    toolsList.appendChild(row);
  });
}

// 🌐 Languages
const languagesList = document.getElementById("languagesList");
let languages = [];
try {
  languages = JSON.parse(data.languages || "[]");
} catch (e) {
  console.error("❌ Error parsing languages:", e);
}

if (languages.length === 0) {
  document.getElementById("languagesSection").style.display = "none";
} else {
  languagesList.innerHTML = "";
  languages.forEach((lang) => {
    const row = document.createElement("div");
    row.className = "skill-row";

    const name = lang.language || "—";
    const level = lang.level || "";

    row.innerHTML = `
      <div class="skill-name">${name}</div>
      <div class="skill-level">${level}</div>
      <div class="skill-dots">
        ${createDots(level, LANGUAGE_LEVEL_MAP, 4)}
      </div>
    `;

    languagesList.appendChild(row);
  });
}

// 📹 Video Link
const videoSection = document.getElementById("videoLinkSection");
const videoDiv = document.getElementById("readonly-video-link");
  if (data.video_link && data.video_link.trim() !== "") {
    if (isPdfExport) {
      const linkText = document.createElement("div");
      linkText.className = "video-link-button";
      linkText.style.background = "transparent";
      linkText.style.border = "none";
    linkText.style.padding = "0";
    linkText.style.boxShadow = "none";
    linkText.style.color = "#003BFF";
    linkText.style.textTransform = "none";
    linkText.style.letterSpacing = "normal";
    linkText.style.fontWeight = "500";
    linkText.textContent = data.video_link;
    videoDiv.innerHTML = "";
    videoDiv.appendChild(linkText);
  } else {
    const button = document.createElement("a");
    button.href = data.video_link;
    button.target = "_blank";
    button.rel = "noopener noreferrer";
    button.className = "video-link-button";
    button.setAttribute("aria-label", "Watch candidate introduction video");
    button.innerHTML = `
      <span class="video-link-icon" aria-hidden="true">▶</span>
      <span>Watch video</span>
    `;
    videoDiv.innerHTML = "";
    videoDiv.appendChild(button);
  }
} else if (videoSection) {
  videoSection.style.display = "none";
}

if (isPdfExport) {
  const container = document.querySelector(".cv-container");
  if (container) {
    const pdfFooter = document.createElement("div");
    pdfFooter.className = "pdf-footer-note";
    pdfFooter.textContent = "Powered by Vintti · All rights reserved.";
    Object.assign(pdfFooter.style, {
      textAlign: "center",
      marginTop: "40px",
      fontSize: "13px",
      color: "#9ca3af",
      textTransform: "uppercase",
      letterSpacing: "0.2em",
    });
    container.appendChild(pdfFooter);
  }
}
    notifyParent(true);
  } catch (error) {
    console.error("❌ Error loading resume data:", error);
    notifyParent(false);
  }
});
document.addEventListener('paste', function (e) {
  const activeEl = document.activeElement;
  if (activeEl && (activeEl.isContentEditable || activeEl.tagName === "INPUT" || activeEl.tagName === "TEXTAREA")) {
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData('text/plain');
    document.execCommand("insertText", false, text);
  }
});
function cleanInlineStyles(element) {
  element.querySelectorAll('*').forEach(el => {
    el.removeAttribute('style');
    el.style.fontFamily = 'Onest, sans-serif';
  });
}
function sortByEndDateDescending(entries) {
  return entries.sort((a, b) => {
    const dateA = a.current || !a.end_date ? new Date(2100, 0, 1) : new Date(a.end_date);
    const dateB = b.current || !b.end_date ? new Date(2100, 0, 1) : new Date(b.end_date);
    return dateB - dateA; // más reciente primero
  });
}
function cleanHTML(html) {
  const wrapper = document.createElement('div');
  wrapper.innerHTML = html;

  // 🔥 Elimina todos los span pero conserva su contenido interno
  wrapper.querySelectorAll('span').forEach(span => {
    const parent = span.parentNode;
    while (span.firstChild) parent.insertBefore(span.firstChild, span);
    parent.removeChild(span);
  });

  // 🔧 Elimina clases raras y estilos inline
  wrapper.querySelectorAll('*').forEach(el => {
    el.removeAttribute('style');
    el.removeAttribute('data-start');
    el.removeAttribute('data-end');
    el.removeAttribute('class');
    el.style.fontFamily = 'Onest, sans-serif';
    el.style.fontSize = '14px';
    el.style.color = '#333';
    el.style.fontWeight = '400';
  });

  // 🧼 Limpia los <br> dentro de <li>
  wrapper.querySelectorAll('li').forEach(li => {
    li.innerHTML = li.innerHTML
      .replace(/<br\s*\/?>/gi, '')   // elimina <br>
      .replace(/&nbsp;/gi, ' ')     // reemplaza nbsp por espacio normal
      .replace(/\s+/g, ' ')         // colapsa espacios múltiples
      .trim();
  });

  // 🔨 Elimina <br> generales fuera de listas
  wrapper.querySelectorAll('br').forEach(br => br.remove());

  // ✨ Colapsa espacios innecesarios entre etiquetas HTML
  wrapper.innerHTML = wrapper.innerHTML.replace(/>\s+</g, '><');

  return wrapper.innerHTML.trim();
}
function getFlagEmoji(countryName) {
  const flags = {
    "Argentina":"🇦🇷","Bolivia":"🇧🇴","Brazil":"🇧🇷","Chile":"🇨🇱","Colombia":"🇨🇴","Costa Rica":"🇨🇷",
    "Cuba":"🇨🇺","Dominican Republic":"🇩🇴","Ecuador":"🇪🇨","El Salvador":"🇸🇻","Guatemala":"🇬🇹",
    "Honduras":"🇭🇳","Mexico":"🇲🇽","Nicaragua":"🇳🇮","Panama":"🇵🇦","Paraguay":"🇵🇾","Peru":"🇵🇪",
    "Uruguay":"🇺🇾","Venezuela":"🇻🇪","United States":"🇺🇸","Canada":"🇨🇦","Spain":"🇪🇸","Portugal":"🇵🇹",
    "United Kingdom":"🇬🇧","Germany":"🇩🇪","France":"🇫🇷","Italy":"🇮🇹","Netherlands":"🇳🇱","Poland":"🇵🇱",
    "India":"🇮🇳","China":"🇨🇳","Japan":"🇯🇵","Australia":"🇦🇺"
  };
  return flags[countryName] || '';
}
