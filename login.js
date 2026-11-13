const loginForm = document.querySelector("#login-form");
const loginMessage = document.querySelector("#login-message");

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginMessage.hidden = true;
  loginMessage.classList.remove("error");

  const submitButton = loginForm.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  submitButton.querySelector("span").textContent = "…";

  try {
    const response = await fetch(loginForm.action, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
      body: new URLSearchParams(new FormData(loginForm)),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "Не удалось войти. Проверьте данные.");
    }
    window.location.assign("/cabinet");
  } catch (error) {
    loginMessage.textContent = error instanceof TypeError
      ? "Нет соединения с сервером. Запустите server.py и попробуйте снова."
      : error.message;
    loginMessage.classList.add("error");
    loginMessage.hidden = false;
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector("span").textContent = "→";
  }
});
