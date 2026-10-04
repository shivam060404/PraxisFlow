import { expect, test } from "@playwright/test";

test("home route reaches the dashboard shell", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.locator("body")).not.toBeEmpty();
});
