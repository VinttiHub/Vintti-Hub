document.addEventListener("DOMContentLoaded", async () => {
  const urlParams = new URLSearchParams(window.location.search);
  const candidateId = urlParams.get("id");
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

  // Caso normal (sin multi-roles o 1 rol)
  if (!roles || roles.length <= 1) {
    const entry = document.createElement("div");
    entry.className = "resume-entry";
    const startDate = formatDate(exp.start_date);
    const endDate = exp.current ? "Present" : formatDate(exp.end_date);
    entry.innerHTML = `
      <strong>${exp.company || "—"}</strong><br/>
      <span>${exp.title || "—"} (${startDate} – ${endDate})</span><br/>
      <div class="resume-description">${cleanHTML(exp.description || "")}</div>
    `;
    return entry;
  }

  // Caso multi-roles (LinkedIn-like)
  const container = document.createElement("div");
  container.className = "resume-entry multi-company";

  // Rango global de la empresa
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

  const headerHTML = `
    <div class="multi-header">
      <div>
        <div class="company-name">${exp.company || "—"}</div>
        <div class="company-range">
          ${formatDateFromDateObj(overallStart)} – ${overallEnd ? formatDateFromDateObj(overallEnd) : "Present"} · ${roles.length} roles
        </div>
      </div>
    </div>
  `;

  const rolesHTML = roles
    .map((r) => {
      const sd = formatDate(r.start_date);
      const ed = r.current ? "Present" : formatDate(r.end_date);
      const desc = r.description_html ? `<div class="multi-desc">${cleanHTML(r.description_html)}</div>` : "";
      return `
        <div class="multi-role ${r.current ? "current" : ""}">
          <div class="multi-title">${r.title || "—"}</div>
          <div class="multi-dates">${sd} – ${ed}</div>
          ${desc}
        </div>
      `;
    })
    .join("");

  container.innerHTML = headerHTML + `<div class="multi-timeline">${rolesHTML}</div>`;
  return container;
}

/* Pintamos la experiencia (orden existente por fin de contrato) */
sortByEndDateDescending(workExperience).forEach((exp) => {
  workExperienceList.appendChild(renderExperienceEntry(exp));
});

// 🎓 Education
const educationList = document.getElementById("educationList");
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
    const entry = document.createElement("div");
    entry.className = "resume-entry";
    const startDate = formatDate(edu.start_date);
    const endDate = edu.current ? "Present" : formatDate(edu.end_date);
    // 🎓 Education
    const countryHtml = (edu.country && edu.country.trim())
      ? `<div class="edu-country">${getFlagEmoji(edu.country)} ${edu.country}</div>`
      : '';

    entry.innerHTML = `
      <div class="edu-header">
        <strong>${edu.institution || "—"}</strong>
      </div>
      <div class="edu-subheader">
        <span class="edu-title">${edu.title || "—"}</span>
        <span class="edu-dates">${startDate} – ${endDate}</span>
      </div>
      ${countryHtml}
      ${edu.description ? `<div class="resume-description">${edu.description}</div>` : ""}
    `;



    educationList.appendChild(entry);
    // ⬇️ Mostrar países de Education bajo el título
(() => {
  const el = document.getElementById("educationCountry");
  if (!el) return;

  // ordena por más reciente y arma lista única de países (más reciente primero)
  const ordered = sortByEndDateDescending([...(education || [])])
    .map(e => (e.country || '').trim())
    .filter(Boolean);

  const seen = new Set();
  const unique = ordered.filter(c => !seen.has(c) && seen.add(c));

  if (unique.length) {
    const pretty = unique
      .map(c => `${getFlagEmoji(c)} ${c}`.trim())
      .join(' · ');
    el.textContent = `Education: ${pretty}`;
    el.style.display = '';
  } else {
    el.style.display = 'none';
  }
})();

  });
}

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
  tools.forEach((tool) => {
    const wrapper = document.createElement("div");
    wrapper.className = "tool-pill";
    const name = typeof tool === "object" ? tool.tool : tool;
    const level = typeof tool === "object" && tool.level ? tool.level : "";
    wrapper.innerHTML = `
      <div class="tool-name">${name}</div>
      <div class="tool-level">${level}</div>
    `;
    toolsList.appendChild(wrapper);
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
  languages.forEach((lang) => {
    const wrapper = document.createElement("div");
    wrapper.className = "tool-pill";
    wrapper.innerHTML = `
      <div class="tool-name">${lang.language || '—'}</div>
      <div class="tool-level">${lang.level || ''}</div>
    `;
    languagesList.appendChild(wrapper);
  });
}

    // 📹 Video Link
    const videoDiv = document.getElementById("readonly-video-link");
    if (data.video_link && data.video_link.trim() !== "") {
      const link = document.createElement("a");
      link.href = data.video_link;
      link.target = "_blank";
      link.textContent = data.video_link;
      videoDiv.innerHTML = "";
      videoDiv.appendChild(link);
    } else {
      videoDiv.closest(".cv-section").style.display = "none";
    }
  } catch (error) {
    console.error("❌ Error loading resume data:", error);
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

