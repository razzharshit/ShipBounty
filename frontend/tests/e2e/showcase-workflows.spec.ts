import { expect, test, type Page } from "@playwright/test";

const workspace = process.env.E2E_DEMO_WORKSPACE;
const accessKey = process.env.E2E_DEMO_ACCESS_KEY;
const prId = process.env.E2E_PR_ID;

async function login(page: Page, persona = "Owner") {
  test.skip(
    !workspace || !accessKey,
    "Set E2E_DEMO_WORKSPACE and E2E_DEMO_ACCESS_KEY for authenticated workflows.",
  );
  await page.goto("/login");
  await page.getByRole("button", { name: persona }).click();
  await page.getByLabel("Workspace").fill(workspace!);
  await page.getByLabel("Demo access key").fill(accessKey!);
  await page.getByRole("button", { name: `Enter as ${persona}` }).click();
  await expect(page).toHaveURL(/\/demo$/);
}

test("login page exposes GitHub authentication", async ({ page }) => {
  await page.goto("/login");
  await expect(
    page.getByRole("heading", { name: "Sign in to your organization" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Continue with GitHub" }),
  ).toBeVisible();
});

test("demo login and organization selection", async ({ page }) => {
  await login(page);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/dashboard\/[^/]+\/product$/);
  await expect(page.getByLabel("Organization").first()).toBeVisible();
});

test("organization switcher changes tenant routes", async ({ page }) => {
  await login(page);
  await page.goto(`/dashboard/${encodeURIComponent(workspace!)}/product`);
  const selector = page.getByLabel("Organization").first();
  const options = await selector.locator("option").all();
  test.skip(options.length < 2, "This showcase account has one organization.");
  const nextValue = await options[1].getAttribute("value");
  await selector.selectOption(nextValue!);
  await expect(page).toHaveURL(
    new RegExp(`/dashboard/${encodeURIComponent(nextValue!)}/product$`),
  );
});

test("review and approval controls render for policy roles", async ({ page }) => {
  test.skip(!prId, "Set E2E_PR_ID to exercise pull-request workflows.");
  await login(page, "Reviewer");
  await page.goto(`/pull-requests/${prId}#human-review`);
  await expect(page.getByRole("heading", { name: "Human review" })).toBeVisible();
  const reviewButton = page.getByRole("button", {
    name: "Record immutable review",
  });
  const noAction = page.getByText(
    "No action is available for your organization role",
  );
  await expect(reviewButton.or(noAction)).toBeVisible();
});

test("AI failure feedback is inline instead of an error page", async ({
  page,
}) => {
  test.skip(!prId, "Set E2E_PR_ID to exercise pull-request workflows.");
  await login(page);
  await page.goto(
    `/pull-requests/${prId}?action_error=${encodeURIComponent(
      "The external provider is temporarily unavailable.",
    )}#ai-review`,
  );
  await expect(page.getByRole("alert")).toContainText(
    "temporarily unavailable",
  );
});

test("pagination preserves an accessible previous action", async ({ page }) => {
  await login(page);
  await page.goto(
    `/dashboard/${encodeURIComponent(workspace!)}/ai-reviews?offset=50`,
  );
  await expect(
    page.getByRole("navigation", { name: "Collection pagination" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Previous" })).toBeVisible();
});

test("notification read state and keyboard command palette", async ({
  page,
}) => {
  await login(page);
  await page.goto(`/dashboard/${encodeURIComponent(workspace!)}/product`);
  await page.getByRole("button", { name: "Open notifications" }).click();
  const markRead = page.getByRole("button", { name: "Mark as read" });
  if (await markRead.count()) {
    await markRead.first().click();
    await expect(markRead.first()).toBeHidden();
  }
  await page.keyboard.press("Escape");
  await page.keyboard.press("ControlOrMeta+K");
  const search = page.getByLabel("Search commands");
  await expect(search).toBeVisible();
  await search.fill("review");
  await expect(page.getByRole("button", { name: /Review queue/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(search).toBeHidden();
});

test("mobile navigation opens and closes", async ({ page }) => {
  await login(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/dashboard/${encodeURIComponent(workspace!)}/product`);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("link", { name: "Review queue" })).toBeVisible();
  await page.getByRole("button", { name: "Close navigation" }).last().click();
  await expect(page.getByRole("link", { name: "Review queue" })).toBeHidden();
});
