const modeButtons = document.querySelectorAll(".segmented button");
const modeDisplays = {
  recommended: document.querySelector(".recommended-mode"),
  compact: document.querySelector(".compact-mode"),
  explicit: document.querySelector(".explicit-mode"),
};

modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    modeButtons.forEach((item) => item.classList.remove("selected"));
    button.classList.add("selected");

    Object.values(modeDisplays).forEach((display) => {
      if (display) {
        display.hidden = true;
      }
    });

    const targetDisplay = modeDisplays[button.dataset.mode];
    if (targetDisplay) {
      targetDisplay.hidden = false;
    }
  });
});

const dialog = document.querySelector("#versionDialog");
const closeDialog = document.querySelector("#closeDialog");
const dialogTriggers = document.querySelectorAll(".doc-link, #compactChip");

if (dialog && closeDialog) {
  dialogTriggers.forEach((trigger) => {
    trigger.addEventListener("click", () => {
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
    });
  });

  closeDialog.addEventListener("click", () => {
    dialog.close();
  });
}
