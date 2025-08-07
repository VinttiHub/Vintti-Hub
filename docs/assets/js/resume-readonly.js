document.addEventListener("DOMContentLoaded", async () => {
  const urlParams = new URLSearchParams(window.location.search);
  const candidateId = urlParams.get("id");
    function formatDate(dateStr) {
      if (!dateStr) return "?";
      const [year, month] = dateStr.split("-"); // Ignora el día
      const date = new Date(`${year}-${month}-01T12:00:00Z`); // Forzamos día seguro en UTC para evitar desbordes
      return date.toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
      });
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
    const aboutP = document.getElementById("aboutField");
    aboutP.textContent = data.about || "—";

// 💼 Work Experience
const workExperienceList = document.getElementById("workExperienceList");
let workExperience = [];
try {
  workExperience = JSON.parse(data.work_experience || "[]");
} catch (e) {
  console.error("❌ Error parsing work_experience:", e);
}
sortByEndDateDescending(workExperience).forEach((exp) => {
  const entry = document.createElement("div");
  const startDate = formatDate(exp.start_date);
  const endDate = exp.current ? "Present" : formatDate(exp.end_date);
  entry.className = "resume-entry";
  // 💼 Work Experience
  entry.innerHTML = `
    <strong>${exp.company || "—"}</strong><br/>
    <span>${exp.title || "—"} (${startDate} – ${endDate})</span><br/>
    <div class="resume-description">${cleanHTML(exp.description || "")}</div>
  `;

  workExperienceList.appendChild(entry);
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
entry.innerHTML = `
  <div class="edu-header">
    <strong>${edu.institution || "—"}</strong>
  </div>
  <div class="edu-subheader">
    <span class="edu-title">${edu.title || "—"}</span>
    <span class="edu-dates">${startDate} – ${endDate}</span>
  </div>
  ${edu.description ? `<div class="resume-description">${edu.description}</div>` : ""}
`;


    educationList.appendChild(entry);
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
const aboutP = document.getElementById("aboutField");
aboutP.innerHTML = data.about || "—";
cleanInlineStyles(aboutP);
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
      .replace(/<br\s*\/?>/gi, '') // remueve todos los br
      .trim();
  });

  // 🔨 Elimina <br> generales fuera de listas
  wrapper.querySelectorAll('br').forEach(br => br.remove());

  return wrapper.innerHTML.trim();
}

