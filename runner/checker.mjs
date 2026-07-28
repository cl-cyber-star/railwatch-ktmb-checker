import { chromium } from "playwright";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const required = [
  "RAILWATCH_API_URL",
  "RAILWATCH_CHECKER_SECRET",
  "OAI_SITES_AUTHORIZATION",
  "KTMB_STORAGE_STATE_B64",
];

for (const name of required) {
  if (!process.env[name]) throw new Error(`Missing required secret: ${name}`);
}

const API_URL = process.env.RAILWATCH_API_URL.replace(/\/$/, "");
const apiHeaders = {
  authorization: `Bearer ${process.env.RAILWATCH_CHECKER_SECRET}`,
  "content-type": "application/json",
  "OAI-Sites-Authorization": `Bearer ${process.env.OAI_SITES_AUTHORIZATION}`,
};

const tempDir = await mkdtemp(join(tmpdir(), "railwatch-"));
const storageStatePath = join(tempDir, "ktmb-storage-state.json");
await writeFile(
  storageStatePath,
  Buffer.from(process.env.KTMB_STORAGE_STATE_B64, "base64"),
  { mode: 0o600 },
);

const response = await fetch(`${API_URL}/api/checker`, {
  headers: apiHeaders,
});
if (!response.ok) throw new Error(`Monitor API returned ${response.status}`);
const { monitors = [] } = await response.json();

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  storageState: storageStatePath,
  locale: "en-MY",
  timezoneId: "Asia/Kuala_Lumpur",
});

try {
  for (const monitor of monitors) {
    let result;
    try {
      result = await checkMonitor(context, monitor);
    } catch (error) {
      result = {
        monitorId: monitor.id,
        availableSeats: 0,
        matchingTrains: [],
        error: error instanceof Error ? error.message : String(error),
      };
    }

    const update = await fetch(`${API_URL}/api/checker`, {
      method: "POST",
      headers: apiHeaders,
      body: JSON.stringify(result),
    });
    if (!update.ok) {
      throw new Error(
        `Result API returned ${update.status} for monitor ${monitor.id}`,
      );
    }
  }
} finally {
  await context.close();
  await browser.close();
}

async function checkMonitor(context, monitor) {
  const page = await context.newPage();
  try {
    await page.goto("https://online.ktmb.com.my/", {
      waitUntil: "domcontentloaded",
      timeout: 45_000,
    });

    const accountButton = page.locator("nav button").filter({
      hasText: /[A-Z]{2,}\s+[A-Z]{2,}/,
    });
    if ((await accountButton.count()) === 0) {
      throw new Error("KTMB session expired; reconnect the stored session.");
    }

    await page.selectOption("#FromStationId", monitor.originId);
    await page.waitForSelector(
      `#ToStationId option[value="${monitor.destinationId}"]`,
      { timeout: 15_000 },
    );
    await page.selectOption("#ToStationId", monitor.destinationId);

    const displayDate = new Intl.DateTimeFormat("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      timeZone: "Asia/Kuala_Lumpur",
    }).format(new Date(`${monitor.travelDate}T12:00:00+08:00`));

    await page.evaluate((value) => {
      const input = document.querySelector("#OnwardDate");
      if (!(input instanceof HTMLInputElement)) {
        throw new Error("KTMB departure field was not found.");
      }
      input.value = value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }, displayDate);

    await Promise.all([
      page.waitForURL(/\/Trip(?:$|\?)/, { timeout: 45_000 }),
      page.locator("#btnSubmit").click(),
    ]);
    await page.waitForSelector("tr", { timeout: 30_000 });

    const rows = page.locator("tbody tr").filter({ hasText: "Pick Seats" });
    const rowCount = await rows.count();
    const matchingTrains = [];

    for (let index = 0; index < rowCount; index += 1) {
      const row = rows.nth(index);
      const cells = await row.locator("td").allTextContents();
      const service = cells[0]?.trim() ?? "";
      const departure = cells[1]?.trim() ?? "";
      if (!inWindow(departure, monitor.startTime, monitor.endTime)) continue;

      await row.getByText("Pick Seats", { exact: true }).click();
      await page.waitForSelector("#seatSelect.show img", { timeout: 30_000 });

      const ordinarySeats = await page
        .locator("#seatSelect img.selectable-icon[data-seat-data]")
        .evaluateAll((images) =>
          images.filter((image) => {
            const src = image.getAttribute("src") ?? "";
            const id = new URL(src, location.origin).searchParams.get("id") ?? "";
            return /^(Stan|Std)/i.test(id) && !/OKU/i.test(id);
          }).length,
        );

      if (ordinarySeats > 0) {
        matchingTrains.push({ service, departure, ordinarySeats });
      }

      await page.locator("#seatSelect button.close").click();
      await page.waitForSelector("#seatSelect", { state: "hidden" });
    }

    return {
      monitorId: monitor.id,
      availableSeats: matchingTrains.reduce(
        (sum, train) => sum + train.ordinarySeats,
        0,
      ),
      matchingTrains,
    };
  } finally {
    await page.close();
  }
}

function inWindow(value, start, end) {
  return /^\d{2}:\d{2}$/.test(value) && value >= start && value <= end;
}
