const form = document.querySelector(".registration-form");
const message = document.querySelector("#registration-message");
const doctorGrid = document.querySelector(".doctor-grid");
if (doctorGrid) {
  fetch("/api/patient/doctors", { cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error("Не удалось загрузить список врачей.");
      return response.json();
    })
    .then(({ doctors }) => {
      for (const doctor of doctors.filter((item) => item.is_registered)) {
        const card = document.createElement("article");
        card.className = "doctor-card";

        const portrait = document.createElement("div");
        portrait.className = "doctor-image registered-doctor-portrait";
        const initials = document.createElement("span");
        initials.textContent = doctor.name.split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
        portrait.append(initials);

        const info = document.createElement("div");
        info.className = "doctor-info";
        const specialty = document.createElement("div");
        specialty.className = "doctor-specialty";
        specialty.textContent = doctor.specialty;
        const name = document.createElement("h3");
        name.textContent = doctor.name;
        const description = document.createElement("p");
        description.textContent = "Профиль врача портала";

        const bottom = document.createElement("div");
        bottom.className = "doctor-bottom";
        const status = document.createElement("span");
        status.className = "doctor-rating";
        status.textContent = "Запись онлайн";
        const bookingLink = document.createElement("a");
        bookingLink.href = `/patient/register?doctor=${encodeURIComponent(doctor.slug)}`;
        bookingLink.textContent = "Записаться →";
        bottom.append(status, bookingLink);
        info.append(specialty, name, description, bottom);
        card.append(portrait, info);
        doctorGrid.append(card);
      }
    })
    .catch((error) => {
      console.error(error);
      const notice = document.createElement("p");
      notice.className = "form-message error";
      notice.textContent = "Не удалось загрузить список зарегистрированных врачей.";
      doctorGrid.after(notice);
    });
}

if (form) form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.hidden = true;
  message.classList.remove("error");

  const submitButton = form.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  submitButton.querySelector("span").textContent = "…";

  try {
    const response = await fetch(form.action, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
      body: new URLSearchParams(new FormData(form)),
    });
    const result = await response.json();

    if (!response.ok) {
      throw new Error(result.error || "Не удалось создать кабинет. Попробуйте ещё раз.");
    }

    window.location.assign("/cabinet");
  } catch (error) {
    message.textContent = error instanceof TypeError
      ? "Не удалось связаться с сервером портала. Запустите server.py и попробуйте снова."
      : error.message;
    message.classList.add("error");
    message.hidden = false;
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector("span").textContent = "→";
  }
});
