import { spawn } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";
import { chromium } from "playwright";

const browser = await launchInstalledBrowser();
const context = await browser.newContext({
  locale: "en-MY",
  timezoneId: "Asia/Kuala_Lumpur",
});
const page = await context.newPage();
const prompt = createInterface({ input, output });

try {
  console.log("Opening the official KTMB sign-in page...");
  await page.goto("https://online.ktmb.com.my/Account/Login", {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });

  await prompt.question(
    "Sign in completely in the browser window. When your KTMB account page is visible, return here and press Enter.",
  );

  await page.goto("https://online.ktmb.com.my/", {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });

  const signedOut =
    (await page.getByText(/Login\s*\/\s*sign up/i).count()) > 0 ||
    /\/Account\/Login/i.test(page.url());

  if (signedOut) {
    throw new Error(
      "KTMB still appears signed out. Run the capture again and complete every login or verification step before pressing Enter.",
    );
  }

  const state = await context.storageState();
  const encoded = Buffer.from(JSON.stringify(state), "utf8").toString("base64");

  if (await copyToClipboard(encoded)) {
    console.log(
      "\nSuccess. The KTMB session is on your clipboard. Paste it directly into the GitHub secret named KTMB_STORAGE_STATE_B64.",
    );
    console.log(
      "Do not paste it into chat, a repository file, an issue, or a workflow log.",
    );
  } else {
    const fallback = ".railwatch-session-secret.txt";
    await writeFile(fallback, encoded, { mode: 0o600 });
    console.log(
      `\nClipboard access was unavailable. The session was saved locally as ${fallback}.`,
    );
    console.log(
      "Copy its full contents into the GitHub secret named KTMB_STORAGE_STATE_B64, then permanently delete the file.",
    );
  }
} finally {
  prompt.close();
  await context.close();
  await browser.close();
}

async function launchInstalledBrowser() {
  const channels = ["msedge", "chrome"];
  let lastError;

  for (const channel of channels) {
    try {
      return await chromium.launch({ channel, headless: false });
    } catch (error) {
      lastError = error;
    }
  }

  throw new Error(
    "Microsoft Edge or Google Chrome could not be opened. Install one of them and run this command again.",
    { cause: lastError },
  );
}

async function copyToClipboard(value) {
  const command =
    process.platform === "win32"
      ? ["clip.exe", []]
      : process.platform === "darwin"
        ? ["pbcopy", []]
        : null;

  if (!command) return false;

  return new Promise((resolve) => {
    const child = spawn(command[0], command[1], {
      stdio: ["pipe", "ignore", "ignore"],
    });
    child.on("error", () => resolve(false));
    child.on("close", (code) => resolve(code === 0));
    child.stdin.end(value);
  });
}
