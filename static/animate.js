const burger = document.querySelector(".bandeau .burger");
const menu = document.querySelector(".bandeau .menu");

burger.addEventListener("mouseenter", () => {
  menu.classList.add("show");
});

burger.addEventListener("mouseleave", () => {
  setTimeout(() => {
    if (!menu.matches(":hover")) menu.classList.remove("show");
  }, 100);
});

menu.addEventListener("mouseleave", () => {
  menu.classList.remove("show");
});
