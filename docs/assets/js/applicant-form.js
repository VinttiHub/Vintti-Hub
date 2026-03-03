const API_BASE =
  (location.hostname === "127.0.0.1" || location.hostname === "localhost")
    ? "http://127.0.0.1:5000"
    : "https://7m6mw95m8y.us-east-2.awsapprunner.com";

const form = document.getElementById("applicantForm");
const cvInput = document.getElementById("cvInput");
const cvButton = document.getElementById("cvButton");
const cvFilename = document.getElementById("cvFilename");
const formStatus = document.getElementById("formStatus");
const submitBtn = document.getElementById("submitBtn");
const toast = document.getElementById("toast");
const steps = Array.from(document.querySelectorAll(".form-step"));
const stepTitle = document.getElementById("stepTitle");
const stepIndex = document.getElementById("stepIndex");
const stepTotal = document.getElementById("stepTotal");
const progressFill = document.getElementById("progressFill");
const stepDots = document.getElementById("stepDots");
const backBtn = document.querySelector('[data-action="back"]');
const nextBtn = document.querySelector('[data-action="next"]');
let toastTimer = null;
let currentStep = 0;

function applyPrefillFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const roleValue = (params.get("role_position") || "").trim();
  const areaValue = (params.get("area") || "").trim();
  const opportunityValue = (params.get("opportunity_id") || "").trim();

  if (roleValue) {
    const roleInput = form?.elements?.["role_position"];
    if (roleInput && !roleInput.value) roleInput.value = roleValue;
  }

  if (areaValue) {
    const areaInput = form?.elements?.["area"];
    if (areaInput && !areaInput.value) areaInput.value = areaValue;
  }

  if (opportunityValue) {
    const oppInput = document.getElementById("opportunityId");
    if (oppInput) oppInput.value = opportunityValue;
  }
}

function setStatus(message, tone) {
  formStatus.textContent = message;
  formStatus.classList.remove("success", "error");
  if (tone) formStatus.classList.add(tone);
}

function showToast(message) {
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("is-visible");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.remove("is-visible");
  }, 3500);
}

cvButton.addEventListener("click", () => {
  cvInput.click();
});

cvInput.addEventListener("change", () => {
  const file = cvInput.files && cvInput.files[0];
  cvFilename.textContent = file ? file.name : "No file selected";
});

function buildStepDots() {
  if (!stepDots) return;
  stepDots.innerHTML = "";
  steps.forEach(() => {
    const dot = document.createElement("span");
    stepDots.appendChild(dot);
  });
}

function updateSteps() {
  steps.forEach((step, index) => {
    const isActive = index === currentStep;
    step.classList.toggle("is-active", isActive);
    step.classList.toggle("is-complete", index < currentStep);
    step.setAttribute("aria-hidden", String(!isActive));
  });

  const activeStep = steps[currentStep];
  if (stepTitle && activeStep) {
    stepTitle.textContent = activeStep.dataset.title || `Step ${currentStep + 1}`;
  }
  if (stepIndex) stepIndex.textContent = String(currentStep + 1);
  if (stepTotal) stepTotal.textContent = String(steps.length);
  if (progressFill) {
    const progress = ((currentStep + 1) / steps.length) * 100;
    progressFill.style.width = `${progress}%`;
  }
  if (stepDots) {
    [...stepDots.children].forEach((dot, index) => {
      dot.classList.toggle("is-active", index === currentStep);
      dot.classList.toggle("is-complete", index < currentStep);
    });
  }
  if (backBtn) backBtn.disabled = currentStep === 0;
  if (nextBtn) nextBtn.style.display = currentStep === steps.length - 1 ? "none" : "inline-flex";
  if (submitBtn) submitBtn.style.display = currentStep === steps.length - 1 ? "inline-flex" : "none";
}

function validateStep(index) {
  const step = steps[index];
  if (!step) return true;
  const fields = step.querySelectorAll("input, select, textarea");
  for (const field of fields) {
    if (!field.checkValidity()) {
      field.reportValidity();
      return false;
    }
  }
  return true;
}

function goToStep(nextIndex) {
  currentStep = Math.max(0, Math.min(nextIndex, steps.length - 1));
  setStatus("", "");
  updateSteps();
}

applyPrefillFromQuery();
buildStepDots();
updateSteps();

backBtn?.addEventListener("click", () => {
  goToStep(currentStep - 1);
});

nextBtn?.addEventListener("click", () => {
  if (!validateStep(currentStep)) return;
  goToStep(currentStep + 1);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (currentStep < steps.length - 1) {
    if (validateStep(currentStep)) {
      goToStep(currentStep + 1);
    }
    return;
  }

  if (submitBtn.disabled) return;

  if (!form.reportValidity()) return;

  setStatus("Submitting...", "");
  submitBtn.disabled = true;

  try {
    const payload = new FormData(form);
    const response = await fetch(`${API_BASE}/applicants`, {
      method: "POST",
      body: payload,
    });

    if (!response.ok) {
      const text = await response.text().catch(() => "");
      setStatus(text || "Something went wrong. Please try again.", "error");
      submitBtn.disabled = false;
      return;
    }

    setStatus("", "");
    showToast("Application received. We will be in touch soon.");
    form.reset();
    cvFilename.textContent = "No file selected";
  } catch (err) {
    setStatus("Unable to submit right now. Please try again.", "error");
  } finally {
    submitBtn.disabled = false;
  }
});
