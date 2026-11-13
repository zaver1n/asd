const profileForm = document.querySelector("#profile-form");
const profileMessage = document.querySelector("#profile-message");
const logoutButton = document.querySelector("#logout-button");
const appointmentList = document.querySelector("#doctor-appointment-list");
const appointmentMessage = document.querySelector("#doctor-appointment-message");

function showProfileMessage(text, isError = false) {
  profileMessage.textContent = text;
  profileMessage.classList.toggle("error", isError);
  profileMessage.hidden = false;
}

async function loadProfile() {
  let response;
  try {
    response = await fetch("/api/me", { cache: "no-store" });
  } catch {
    document.querySelector(".cabinet-main").innerHTML =
      '<div class="container"><p class="form-message error">Нет соединения с сервером. Запустите server.py и обновите страницу.</p></div>';
    return;
  }
  if (response.status === 401) {
    window.location.replace("/login");
    return;
  }
  if (!response.ok) {
    showProfileMessage("Не удалось загрузить профиль. Обновите страницу.", true);
    return;
  }

  const { doctor } = await response.json();
  for (const [name, value] of Object.entries(doctor)) {
    const field = profileForm.elements.namedItem(name);
    if (field) field.value = value;
  }
  document.querySelector("#doctor-greeting").textContent = doctor.first_name;
  document.querySelector("#profile-avatar").textContent = doctor.first_name.charAt(0).toUpperCase();
  document.querySelector("#side-specialty").textContent = doctor.specialty;
  const memberSince = new Date(doctor.created_at);
  document.querySelector("#member-since").textContent = new Intl.DateTimeFormat("ru-RU", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(memberSince);
  await loadDoctorAppointments();
}

async function loadDoctorAppointments() {
  const response = await fetch("/api/doctor/appointments", { cache: "no-store" });
  if (response.status === 401) {
    window.location.replace("/login");
    return;
  }
  if (!response.ok) throw new Error("Не удалось загрузить записи пациентов.");

  const { appointments } = await response.json();
  document.querySelector("#pending-count").textContent =
    `${appointments.filter((item) => item.status === "pending").length} ожидают`;
  appointmentList.replaceChildren();
  if (appointments.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-appointments";
    empty.innerHTML = '<span class="empty-icon" aria-hidden="true">＋</span><strong>Записей пока нет</strong><span>Новые записи пациентов появятся здесь.</span>';
    appointmentList.append(empty);
    return;
  }

  for (const appointment of appointments) {
    const card = document.createElement("article");
    card.className = "doctor-appointment-item";
    const details = document.createElement("div");
    details.className = "doctor-appointment-details";

    const name = document.createElement("strong");
    name.textContent = `${appointment.patient_first_name} ${appointment.patient_last_name}`;
    const when = document.createElement("span");
    when.className = "appointment-datetime";
    const appointmentDate = new Date(`${appointment.appointment_date}T12:00:00`);
    when.textContent = `${new Intl.DateTimeFormat("ru-RU", {
      day: "numeric",
      month: "long",
      year: "numeric",
    }).format(appointmentDate)} · ${appointment.appointment_time}`;
    const phone = document.createElement("a");
    phone.className = "patient-phone";
    phone.href = `tel:${appointment.patient_phone.replace(/[^\d+]/g, "")}`;
    phone.textContent = appointment.patient_phone;
    details.append(name, when, phone);

    if (appointment.note) {
      const note = document.createElement("p");
      note.className = "doctor-appointment-note";
      note.textContent = appointment.note;
      details.append(note);
    }

    const actions = document.createElement("div");
    actions.className = "doctor-appointment-actions";
    const status = document.createElement("span");
    status.className = `appointment-status ${appointment.status}`;
    const statusLabels = {
      pending: "Ожидает подтверждения",
      confirmed: "Подтверждена",
      rejected: "Отклонена",
      cancelled: "Отменена",
    };
    status.textContent = statusLabels[appointment.status] || "Статус не определён";
    actions.append(status);
    if (appointment.status === "pending") {
      const confirm = document.createElement("button");
      confirm.type = "button";
      confirm.className = "button button-primary confirm-appointment";
      confirm.textContent = "Подтвердить";
      confirm.addEventListener("click", () => updateAppointmentStatus(appointment.id, "confirmed", confirm));
      actions.append(confirm);
      const reject = document.createElement("button");
      reject.type = "button";
      reject.className = "button appointment-action-secondary";
      reject.textContent = "Отклонить";
      reject.addEventListener("click", () => {
        if (window.confirm("Отклонить запись пациента?")) {
          updateAppointmentStatus(appointment.id, "rejected", reject);
        }
      });
      actions.append(reject);
    } else if (appointment.status === "confirmed") {
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "button appointment-action-secondary";
      cancel.textContent = "Отменить приём";
      cancel.addEventListener("click", () => {
        if (window.confirm("Отменить подтверждённый приём?")) {
          updateAppointmentStatus(appointment.id, "cancelled", cancel);
        }
      });
      actions.append(cancel);
    }
    card.append(details, actions);
    appointmentList.append(card);
  }
}

async function updateAppointmentStatus(id, status, button) {
  button.disabled = true;
  appointmentMessage.hidden = true;
  try {
    const response = await fetch(`/api/doctor/appointments/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    const result = await response.json();
    if (response.status === 401) {
      window.location.replace("/login");
      return;
    }
    if (!response.ok) throw new Error(result.error || "Не удалось изменить запись.");
    appointmentMessage.textContent = result.message;
    appointmentMessage.classList.remove("error");
    appointmentMessage.hidden = false;
    await loadDoctorAppointments();
  } catch (error) {
    button.disabled = false;
    appointmentMessage.textContent = error instanceof TypeError
      ? "Нет соединения с сервером."
      : error.message;
    appointmentMessage.classList.add("error");
    appointmentMessage.hidden = false;
  }
}

profileForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  profileMessage.hidden = true;
  const submitButton = profileForm.querySelector('button[type="submit"]');
  submitButton.disabled = true;

  const data = Object.fromEntries(new FormData(profileForm));
  try {
    const response = await fetch("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    const result = await response.json();
    if (response.status === 401) {
      window.location.replace("/login");
      return;
    }
    if (!response.ok) throw new Error(result.error || "Не удалось сохранить профиль.");
    showProfileMessage(result.message);
    document.querySelector("#doctor-greeting").textContent = data.first_name;
    document.querySelector("#profile-avatar").textContent = data.first_name.charAt(0).toUpperCase();
    document.querySelector("#side-specialty").textContent = data.specialty;
  } catch (error) {
    showProfileMessage(error instanceof TypeError ? "Нет соединения с сервером." : error.message, true);
  } finally {
    submitButton.disabled = false;
  }
});

logoutButton.addEventListener("click", async () => {
  logoutButton.disabled = true;
  try {
    const response = await fetch("/api/logout", { method: "POST" });
    if (!response.ok) throw new Error("Не удалось завершить сеанс.");
    window.location.replace("/");
  } catch {
    logoutButton.disabled = false;
    showProfileMessage("Не удалось выполнить выход. Проверьте соединение и попробуйте снова.", true);
  }
});

loadProfile().catch(() => {
  appointmentMessage.textContent = "Не удалось загрузить записи пациентов. Обновите страницу.";
  appointmentMessage.classList.add("error");
  appointmentMessage.hidden = false;
});
