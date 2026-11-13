const patientRegisterForm = document.querySelector("#patient-register-form");
const patientLoginForm = document.querySelector("#patient-login-form");
const appointmentForm = document.querySelector("#appointment-form");
const patientProfileForm = document.querySelector("#patient-profile-form");

function appointmentRedirect() {
  const doctor = new URLSearchParams(window.location.search).get("doctor");
  return doctor ? `/patient/cabinet?doctor=${encodeURIComponent(doctor)}#booking` : "/patient/cabinet";
}

function showMessage(element, text, isError = false) {
  element.textContent = text;
  element.classList.toggle("error", isError);
  element.hidden = false;
}

async function submitPatientAuth(form) {
  const message = document.querySelector("#patient-auth-message");
  const button = form.querySelector('button[type="submit"]');
  message.hidden = true;
  button.disabled = true;
  try {
    const response = await fetch(form.action, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
      body: new URLSearchParams(new FormData(form)),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Не удалось выполнить запрос.");
    window.location.assign(appointmentRedirect());
  } catch (error) {
    showMessage(
      message,
      error instanceof TypeError ? "Нет соединения с сервером. Попробуйте ещё раз." : error.message,
      true,
    );
  } finally {
    button.disabled = false;
  }
}

if (patientRegisterForm) {
  patientRegisterForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitPatientAuth(patientRegisterForm);
  });
  fetch("/api/patient/session", { cache: "no-store" }).then((response) => {
    if (!response.ok) throw new Error("Не удалось проверить сессию.");
    return response.json();
  }).then(({ authenticated }) => {
    if (authenticated) window.location.replace(appointmentRedirect());
  }).catch(() => {});
}

if (patientLoginForm) {
  patientLoginForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitPatientAuth(patientLoginForm);
  });
}

async function loadPatientCabinet() {
  let response;
  try {
    response = await fetch("/api/patient/me", { cache: "no-store" });
  } catch {
    document.querySelector(".patient-cabinet").innerHTML =
      '<div class="container"><p class="form-message error">Нет соединения с сервером. Обновите страницу и попробуйте снова.</p></div>';
    return;
  }
  if (response.status === 401) {
    const next = new URLSearchParams(window.location.search).get("doctor");
    window.location.replace(next ? `/patient/login?doctor=${encodeURIComponent(next)}` : "/patient/login");
    return;
  }
  if (!response.ok) throw new Error("Не удалось загрузить личный кабинет.");

  const { patient } = await response.json();
  for (const [name, value] of Object.entries(patient)) {
    const field = patientProfileForm.elements.namedItem(name);
    if (field) field.value = value;
  }
  document.querySelector("#patient-greeting").textContent = patient.first_name;
  document.querySelector("#patient-avatar").textContent = patient.first_name.charAt(0).toUpperCase();

  const dateField = document.querySelector("#appointment-date");
  const today = new Date();
  const localToday = new Date(today.getTime() - today.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
  dateField.min = localToday;
  const latestDate = new Date(today);
  latestDate.setFullYear(latestDate.getFullYear() + 1);
  dateField.max = new Date(latestDate.getTime() - latestDate.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);

  const doctorsResponse = await fetch("/api/patient/doctors", { cache: "no-store" });
  if (!doctorsResponse.ok) throw new Error("Не удалось загрузить список врачей.");
  const { doctors } = await doctorsResponse.json();
  const doctorSelect = appointmentForm.elements.doctor_slug;
  doctorSelect.replaceChildren();
  for (const doctor of doctors) {
    const option = document.createElement("option");
    option.value = doctor.slug;
    option.textContent = `${doctor.name} · ${doctor.specialty}`;
    doctorSelect.append(option);
  }

  const selectedDoctor = new URLSearchParams(window.location.search).get("doctor");
  if (selectedDoctor) {
    const doctorOption = Array.from(doctorSelect.options)
      .find((option) => option.value === selectedDoctor);
    if (doctorOption) {
      doctorSelect.value = selectedDoctor;
    } else {
      const noLongerAvailable = document.createElement("option");
      noLongerAvailable.value = selectedDoctor;
      noLongerAvailable.textContent = "Выбранный врач больше не доступен";
      noLongerAvailable.disabled = true;
      noLongerAvailable.selected = true;
      doctorSelect.prepend(noLongerAvailable);
    }
  }
  await loadAppointments();
}

async function loadAppointments() {
  const list = document.querySelector("#appointment-list");
  const response = await fetch("/api/patient/appointments", { cache: "no-store" });
  if (response.status === 401) {
    window.location.replace("/patient/login");
    return;
  }
  if (!response.ok) throw new Error("Не удалось загрузить записи.");
  const { appointments } = await response.json();
  list.replaceChildren();
  if (appointments.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-appointments";
    empty.innerHTML = '<span class="empty-icon" aria-hidden="true">＋</span><strong>У вас пока нет записей</strong><span>Выберите врача и удобное время в форме рядом.</span>';
    list.append(empty);
    return;
  }

  for (const appointment of appointments) {
    const card = document.createElement("article");
    card.className = "appointment-item";
    const details = document.createElement("div");
    details.className = "appointment-item-main";
    const doctor = document.createElement("strong");
    doctor.textContent = appointment.name;
    const specialty = document.createElement("span");
    specialty.className = "appointment-specialty";
    specialty.textContent = appointment.specialty;
    const dateTime = document.createElement("span");
    dateTime.className = "appointment-datetime";
    const parsedDate = new Date(`${appointment.appointment_date}T12:00:00`);
    dateTime.textContent = `${new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric" }).format(parsedDate)} · ${appointment.appointment_time}`;
    details.append(doctor, specialty, dateTime);
    const statusLabels = {
      pending: "Ожидает подтверждения",
      confirmed: "Подтверждена",
      rejected: "Отклонена",
      cancelled: "Отменена врачом",
    };
    const status = document.createElement("span");
    status.className = `appointment-status ${appointment.status}`;
    status.textContent = statusLabels[appointment.status] || "Статус не определён";
    details.append(status);
    if (appointment.note) {
      const note = document.createElement("span");
      note.className = "appointment-note";
      note.textContent = appointment.note;
      details.append(note);
    }
    if (appointment.status === "pending" || appointment.status === "confirmed") {
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "cancel-appointment";
      cancel.textContent = "Отменить";
      cancel.addEventListener("click", () => cancelAppointment(appointment.id, cancel));
      card.append(details, cancel);
    } else {
      card.append(details);
    }
    list.append(card);
  }
}

async function cancelAppointment(id, button) {
  button.disabled = true;
  try {
    const response = await fetch(`/api/patient/appointments/${id}`, { method: "DELETE" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Не удалось отменить запись.");
    await loadAppointments();
  } catch (error) {
    button.disabled = false;
    showMessage(document.querySelector("#appointment-message"), error.message, true);
  }
}

if (appointmentForm) {
  appointmentForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = document.querySelector("#appointment-message");
    const button = appointmentForm.querySelector('button[type="submit"]');
    message.hidden = true;
    button.disabled = true;
    try {
      const response = await fetch(appointmentForm.action, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
        body: new URLSearchParams(new FormData(appointmentForm)),
      });
      const result = await response.json();
      if (response.status === 401) {
        window.location.replace("/patient/login");
        return;
      }
      if (!response.ok) throw new Error(result.error || "Не удалось записаться.");
      appointmentForm.reset();
      showMessage(message, result.message);
      await loadAppointments();
    } catch (error) {
      showMessage(message, error instanceof TypeError ? "Нет соединения с сервером." : error.message, true);
    } finally {
      button.disabled = false;
    }
  });
}

if (patientProfileForm) {
  patientProfileForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = document.querySelector("#patient-profile-message");
    const button = patientProfileForm.querySelector('button[type="submit"]');
    button.disabled = true;
    message.hidden = true;
    try {
      const response = await fetch("/api/patient/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.fromEntries(new FormData(patientProfileForm))),
      });
      const result = await response.json();
      if (response.status === 401) {
        window.location.replace("/patient/login");
        return;
      }
      if (!response.ok) throw new Error(result.error || "Не удалось сохранить данные.");
      showMessage(message, result.message);
      document.querySelector("#patient-greeting").textContent = patientProfileForm.elements.first_name.value;
      document.querySelector("#patient-avatar").textContent = patientProfileForm.elements.first_name.value.charAt(0).toUpperCase();
    } catch (error) {
      showMessage(message, error instanceof TypeError ? "Нет соединения с сервером." : error.message, true);
    } finally {
      button.disabled = false;
    }
  });
}

const patientLogout = document.querySelector("#patient-logout");
if (patientLogout) {
  patientLogout.addEventListener("click", async () => {
    patientLogout.disabled = true;
    try {
      const response = await fetch("/api/patient/logout", { method: "POST" });
      if (!response.ok) throw new Error("Не удалось завершить сеанс.");
      window.location.replace("/");
    } catch {
      patientLogout.disabled = false;
      showMessage(document.querySelector("#appointment-message"), "Не удалось выполнить выход. Попробуйте снова.", true);
    }
  });
}

if (appointmentForm) {
  loadPatientCabinet().catch(() => {
    showMessage(document.querySelector("#appointment-message"), "Не удалось загрузить данные кабинета.", true);
  });
}
