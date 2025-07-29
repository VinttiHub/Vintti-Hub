document.addEventListener("DOMContentLoaded", async () => {
  const urlParams = new URLSearchParams(window.location.search);
  const candidateId = urlParams.get("id");
    function formatDate(dateStr) {
    if (!dateStr) return "?";
    const date = new Date(dateStr);
    if (isNaN(date)) return "?";
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
workExperience.forEach((exp) => {
  const entry = document.createElement("div");
  const startDate = formatDate(exp.start_date);
  const endDate = exp.current ? "Present" : formatDate(exp.end_date);
  entry.className = "resume-entry";
  // 💼 Work Experience
  entry.innerHTML = `
    <strong>${exp.company || "—"}</strong><br/>
    <span>${exp.title || "—"} (${startDate} – ${endDate})</span><br/>
    <div class="resume-description">${exp.description || ""}</div>
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
  education.forEach((edu) => {
    const entry = document.createElement("div");
    entry.className = "resume-entry";
    const startDate = formatDate(edu.start_date);
    const endDate = edu.current ? "Present" : formatDate(edu.end_date);
    // 🎓 Education
    entry.innerHTML = `
      <strong>${edu.institution || "—"}</strong><br/>
      <span style="font-weight: 500;">${edu.title || "—"}</span><br/>
      <span>${startDate} – ${endDate}</span><br/>
      <div class="resume-description">${edu.description || ""}</div>
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
