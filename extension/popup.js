const KTMB_ORIGIN = "https://online.ktmb.com.my";
const CONNECT_URL =
  "https://ktmb-ticket-watch.cheelong99.chatgpt.site/api/ktmb/connect";

const codeInput = document.querySelector("#link-code");
const connectButton = document.querySelector("#connect");
const openButton = document.querySelector("#open-ktmb");
const status = document.querySelector("#status");

openButton.addEventListener("click", () => {
  chrome.tabs.create({ url: `${KTMB_ORIGIN}/` });
});

codeInput.addEventListener("input", () => {
  codeInput.value = cleanCode(codeInput.value);
});

connectButton.addEventListener("click", async () => {
  const code = cleanCode(codeInput.value);
  if (!/^[A-Za-z0-9_-]{32}$/.test(code)) {
    setStatus("Enter the complete 32-character Railwatch code.", "error");
    return;
  }

  connectButton.disabled = true;
  setStatus("Reading the signed-in KTMB session…");
  try {
    const tab = await findKtmbTab();
    if (!tab?.id || !tab.url || /\/Account\/Login(?:$|[?#])/i.test(tab.url)) {
      throw new Error("Sign in on the official KTMB tab before connecting.");
    }

    const [authenticated, storeId, localStorage] = await Promise.all([
      verifyKtmbLogin(tab.id),
      findCookieStore(tab.id),
      readKtmbLocalStorage(tab.id),
    ]);
    if (!authenticated) {
      throw new Error(
        "KTMB is not signed in on this tab. Complete login, wait for the homepage, and retry.",
      );
    }

    const cookieQuery = { domain: "ktmb.com.my" };
    if (storeId) cookieQuery.storeId = storeId;
    const now = Date.now() / 1000;
    const cookies = (await chrome.cookies.getAll(cookieQuery)).filter(
      (cookie) =>
        isKtmbDomain(cookie.domain) &&
        (!cookie.expirationDate || cookie.expirationDate > now),
    );
    if (cookies.length === 0) {
      throw new Error(
        "No authenticated KTMB cookies were found in this browser profile. Complete KTMB login and retry.",
      );
    }

    const storageState = {
      cookies: cookies.map((cookie) => ({
        name: cookie.name,
        value: cookie.value,
        domain: cookie.domain,
        path: cookie.path || "/",
        expires: cookie.expirationDate ?? -1,
        httpOnly: Boolean(cookie.httpOnly),
        secure: Boolean(cookie.secure),
        sameSite: playwrightSameSite(cookie.sameSite),
      })),
      origins: [{ origin: KTMB_ORIGIN, localStorage }],
    };

    setStatus("Encrypting the session in Railwatch…");
    const response = await fetch(CONNECT_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ code, storageState }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(body.error || "Railwatch could not connect this session.");
    }

    codeInput.value = "";
    setStatus("Connected. Railwatch can now check your journeys.", "success");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Connection failed.", "error");
  } finally {
    connectButton.disabled = false;
  }
});

async function findKtmbTab() {
  const tabs = await chrome.tabs.query({ url: `${KTMB_ORIGIN}/*` });
  return tabs.find((tab) => tab.active) ?? tabs.at(-1);
}

async function verifyKtmbLogin(tabId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      const loginPage = /\/Account\/Login(?:$|[?#])/i.test(window.location.href);
      const visibleLoginLink = Array.from(
        document.querySelectorAll('a[href*="/Account/Login"]'),
      ).some((element) => {
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return (
          style.display !== "none" &&
          style.visibility !== "hidden" &&
          Number(style.opacity || "1") > 0 &&
          rect.width > 0 &&
          rect.height > 0
        );
      });
      return !loginPage && !visibleLoginLink;
    },
  });
  return results[0]?.result === true;
}

async function findCookieStore(tabId) {
  const stores = await chrome.cookies.getAllCookieStores();
  return stores.find((store) => store.tabIds.includes(tabId))?.id;
}

function isKtmbDomain(value) {
  const domain = String(value || "").toLowerCase().replace(/^\./, "");
  return domain === "ktmb.com.my" || domain.endsWith(".ktmb.com.my");
}

async function readKtmbLocalStorage(tabId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    func: () =>
      Object.entries(window.localStorage).map(([name, value]) => ({ name, value })),
  });
  return results[0]?.result ?? [];
}

function playwrightSameSite(value) {
  if (value === "strict") return "Strict";
  if (value === "no_restriction") return "None";
  return "Lax";
}

function cleanCode(value) {
  return value.trim().replace(/[^A-Za-z0-9_-]/g, "").slice(0, 32);
}

function setStatus(message, tone = "") {
  status.textContent = message;
  status.className = `status ${tone}`.trim();
}
