// Adds a "Copy" button to each command block. No network calls, no storage.
document.querySelectorAll(".cmd").forEach((block) => {
  const code = block.querySelector("code");
  if (!code || !navigator.clipboard) return;
  const status = document.getElementById("copy-status");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy";
  button.textContent = "Copy";
  button.setAttribute("aria-label", `Copy command: ${code.textContent}`);
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(code.textContent);
      button.textContent = "Copied";
      if (status) status.textContent = "Command copied";
      setTimeout(() => {
        button.textContent = "Copy";
        if (status) status.textContent = "";
      }, 2000);
    } catch {
      button.textContent = "Copy failed";
    }
  });
  block.appendChild(button);
});
