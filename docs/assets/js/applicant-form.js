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

function setStatus(message, tone) {
  formStatus.textContent = message;
  formStatus.classList.remove("success", "error");
  if (tone) formStatus.classList.add(tone);
}

cvButton.addEventListener("click", () => {
  cvInput.click();
});

cvInput.addEventListener("change", () => {
  const file = cvInput.files && cvInput.files[0];
  cvFilename.textContent = file ? file.name : "No file selected";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (submitBtn.disabled) return;

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

    setStatus("Application received. We will be in touch soon.", "success");
    form.reset();
    cvFilename.textContent = "No file selected";
  } catch (err) {
    setStatus("Unable to submit right now. Please try again.", "error");
  } finally {
    submitBtn.disabled = false;
  }
});
